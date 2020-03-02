# Horaro functionality for loading schedule info using their API.

import datetime
import logging
import re

import requests
from django.db.models import Min
from django.utils import dateparse

from tracker.models import SpeedRun, Runner
from tracker.models.event import TimestampField

EVENT_URL = 'https://horaro.org/-/api/v1/events/{event_id}'
SCHEDULES_URL = 'https://horaro.org/-/api/v1/events/{event_id}/schedules'

# Ignore games with this text in the name, i.e. setup blocks, preshow, finale.
IGNORE_LIST = (
    'setup',
    'preshow',
    'pre-show',
    'finale',
)

logger = logging.getLogger(__name__)


class HoraroError(Exception):
    pass


def _get_horaro_data(url):
    r = requests.get(url)

    if r.status_code != 200:
        logger.error("Error getting URL {0!r} - {1}".format(url, r.status_code))
        raise HoraroError(r.status_code)

    data = r.json()
    if data.get('status'):
        logger.error("Error getting URL {0!r} - {1}: {2}".format(url, data.get('status'), data.get('message')))
        raise HoraroError(data.get('status'))

    return data['data']


def get_event_data(event_id):
    """Get Horaro event data.

    :param event_id: Event ID or slug.
    :type event_id: str
    :return: Event data JSON object.
    :rtype: dict
    """
    return _get_horaro_data(EVENT_URL.format(event_id=event_id))


def get_schedule_data(event_id):
    """Get Horaro schedule data for an event.

    :param event_id: Event ID or slug.
    :type event_id: str
    :return: Schedule data JSON array, each element is a JSON object for a schedule.
    :rtype: list[dict]
    """
    return _get_horaro_data(SCHEDULES_URL.format(event_id=event_id))


def merge_event_schedule(event):
    """Merge schedule from Horaro API with an event in our system.

    :param event: Event record to merge.
    :type event: tracker.models.Event
    :return: Number of runs updated.
    :rtype: int
    """
    i = TimestampField.time_string_to_int
    num_runs = 0

    if not event.horaro_id:
        raise HoraroError("Event ID not set")

    if event.horaro_game_col is None:
        raise HoraroError("Game Column not set")

    # Get schedule data.
    schedules = get_schedule_data(event.horaro_id)

    # Get existing runs in a single query.  Clear position for all for re-ordering.
    qs = SpeedRun.objects.select_for_update().filter(event=event)
    qs.update(order=None)
    existing_runs = dict([(r.name, r) for r in qs])

    # Track seen games to make sure there aren't any duplicate games on the schedule.
    games_seen = set()
    order = 0

    # Import each run from the Horaro schedules.
    for schedule in schedules:
        setup = dateparse.parse_duration(schedule['setup'])

        # Load all runs from the schedule.
        for item in schedule['items']:
            order += 1
            num_cols = len(item['data'])

            if num_cols <= event.horaro_game_col:
                logger.error("Game column {} not valid for number of columns from Horaro API {!r}".format(
                    event.horaro_game_col, item['data']))
                raise HoraroError("Game Column not valid")

            game = (item['data'][event.horaro_game_col] or '').strip()

            category = ''

            # Get category if we have a category column.
            if event.horaro_category_col is not None:
                if num_cols <= event.horaro_category_col:
                    logger.error("Category column {} not valid for number of columns from Horaro API {!r}".format(
                        event.horaro_category_col, item['data']))
                    raise HoraroError("Category Column not valid")

                category = (item['data'][event.horaro_category_col] or '').strip()

            # Otherwise, try to detect if the category is part of the game name...
            else:
                i = -1
                for txt in ('any%', '100%'):
                    i = game.lower().find(txt)
                    if i != -1:
                        break

                if i != -1:
                    category = game[i:].strip()
                    game = game[:i].strip()

            # Raise error if we have duplicate games in the schedule.
            # Skip any games with "setup" in the name, i.e. setup blocks.
            unique_name = game.lower()

            ignore = False
            for iname in IGNORE_LIST:
                if re.search(r'\b{}\b'.format(iname), unique_name):
                    ignore = True
                    break

            if ignore:
                logger.debug("Skipping setup item {!r}".format(item['data']))
                continue

            if unique_name in games_seen:
                raise HoraroError("Schedule has duplicate game entry: {!r}".format(game))

            games_seen.add(unique_name)

            # Get commentators if we have a commentators column.
            commentators = ''
            if event.horaro_commentators_col is not None:
                if num_cols <= event.horaro_commentators_col:
                    logger.error("Category column {} not valid for number of columns from Horaro API {!r}".format(
                        event.horaro_commentators_col, item['data']))
                    raise HoraroError("Category Column not valid")

                commentators = (item['data'][event.horaro_commentators_col] or '').strip()

            # Parse runners.
            runners = []
            if event.horaro_runners_col is not None:
                if num_cols <= event.horaro_runners_col:
                    logger.error("Category column {} not valid for number of columns from Horaro API {!r}".format(
                        event.horaro_runners_col, item['data']))
                    raise HoraroError("Category Column not valid")

                parsed_runners = re.split(r',|&|\Wvs\.?\W', (item['data'][event.horaro_runners_col] or '').strip(),
                                          flags=re.IGNORECASE)
                for r in parsed_runners:
                    r = r.strip()

                    # Skip runners that say generic things or are empty.
                    l = set(u.lower() for u in r.split())
                    if not r or l.intersection({'everyone', 'everybody', 'n/a', 'staff'}):
                        continue
                    # Skip if no word characters, ex. "??"
                    elif not re.search(r'\w', r):
                        continue

                    # Try to parse stream links out of runner names based on Horaro link formatting.
                    m = re.search(r'\[([^\]]+)\]\(([^)]+)\)', r)
                    if m:
                        runners.append((m.group(1), m.group(2)))
                    else:
                        runners.append((r, ''))

            runner_names = set(r[0].lower() for r in runners)

            # Check for existing run, or make a new one.
            logger.debug("Merging run: Game {0!r}, category {1!r}, runners {2!r}".format(game, category, runners))

            if game in existing_runs:
                run = existing_runs[game]
            else:
                run = SpeedRun(event=event, name=game)

            run.category = category
            run.commentators = commentators
            run.order = order
            run.setup_time = str(setup)
            run.run_time = str(dateparse.parse_duration(item['length']))
            run.starttime = dateparse.parse_datetime(item['scheduled'])
            run.endtime = run.starttime + datetime.timedelta(milliseconds=i(run.run_time) + i(run.setup_time))
            # Use times from the Horaro schedule.
            run.save(fix_time=False)

            # Make runner records.
            for u in run.runners.all():
                if u.name.lower() not in runner_names:
                    run.runners.remove(u)

            current_runners = run.runners.all()
            for runner, url in runners:
                try:
                    u = Runner.objects.select_for_update().filter(name__iexact=runner).get()
                except Runner.DoesNotExist:
                    u = Runner()

                u.name = runner
                if url:
                    u.stream = url
                u.save()

                if u not in current_runners:
                    run.runners.add(u)

            # Save the run again to update the runners field.
            run.save(fix_time=False)

            # Increment counter.
            num_runs += 1

    # Set event start date based on first run.
    qs = SpeedRun.objects.filter(event=event).aggregate(start_date=Min('starttime'))
    event.datetime = qs['start_date']
    event.save()

    return num_runs
