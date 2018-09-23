# Generated by Django 2.1.1 on 2018-09-23 18:07

import datetime

from django.db import migrations


def backfill_event_datetime(apps, schema_editor):
    # noinspection PyPep8Naming
    Event = apps.get_model('tracker', 'Event')
    db_alias = schema_editor.connection.alias
    for event in Event.objects.using(db_alias).order_by('date'):
        run = event.speedrun_set.order_by('starttime').first()
        print(event.name)
        if run and run.starttime:
            event.datetime = run.starttime
            print('run start %s' % event.datetime.astimezone(event.timezone))
        else:
            event.datetime = event.timezone.localize(datetime.datetime.combine(event.date, datetime.time(12, 0)))
            print('noon default')
        event.save()


class Migration(migrations.Migration):
    dependencies = [
        ('tracker', '0005_add_event_datetime'),
    ]

    operations = [
        migrations.RunPython(backfill_event_datetime, lambda a, b: None)
    ]
