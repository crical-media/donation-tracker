# Views for the public data feed for our tickers.

from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.utils import timezone
from django.views.generic.base import View

from tracker import viewutil, filters


class UpcomingRunsView(View):
    def get(self, request, event, *args, **kwargs):
        # Get the next 3 upcoming runs for the event that haven't finished yet.
        event = viewutil.get_event(event)
        now = timezone.now()
        params = {
            'event': event.id,
            'endtime_gte': now,
        }
        runs = filters.run_model_query('run', params)[:3]

        results = []
        for run in runs:
            results.append({
                'game': run.name,
                'category': run.category,
                'estimate': str(run.run_time),
                'runners': [r.name for r in run.runners.all()],
            })

        return JsonResponse({'results': results})


class UpcomingBidsView(View):
    def get(self, request, event, *args, **kwargs):
        # Get the upcoming bids and their options + totals.
        event = viewutil.get_event(event)
        # now = timezone.now()
        params = {
            'event': event.id,
            'state': 'OPENED',
        }
        # .filter(speedrun__endtime__gte=now)
        bids = filters.run_model_query('bid', params).select_related(
            'speedrun').prefetch_related('options').order_by('speedrun__endtime')
        results = []

        for bid in bids:
            # ignore bids for no game for now
            if bid.speedrun == None:
                continue
            result = {
                'game': bid.speedrun.name,
                'bid': bid.name,
                'goal': None if bid.goal == None else float(bid.goal),
                'amount_raised': float(bid.total),
                'allow_custom_options': bid.allowuseroptions,
                'options': [],
            }
            for option in bid.options.filter(state='OPENED'):
                result['options'].append({
                    'name': option.name,
                    'amount_raised': float(option.total),
                })
                result['amount_raised'] += float(option.total)

            results.append(result)

        return JsonResponse({'results': results})

class RecentDonationsView(View):
    def get(self, request, event, *args, **kwargs):
        event = viewutil.get_event(event)
        params = {
            'event': event.id,
            'transactionstate':'COMPLETED',
        }
        # get all completed donations, get the last 20 recieved ones
        donations = filters.run_model_query('donation', params).select_related('donor').order_by('-timereceived')[:20]
        results = []
        for donation in donations:
            results.append({
                'id': donation.id,
                'donor': donation.donor.visible_name(),
                'comment': donation.comment if donation.commentstate == 'APPROVED' else '',
                'amount': float(donation.amount),
            })
        return JsonResponse({'results':results})




class CurrentDonationsView(View):
    def get(self, request, event, *args, **kwargs):
        event = viewutil.get_event(event)
        params = {
            'event': event.id,
            'transactionstate':'COMPLETED',
        }
        agg = filters.run_model_query('donation', params).aggregate(amount=Coalesce(Sum('amount'), Decimal('0.00')))

        print(type(agg["amount"]))

        return JsonResponse({
            'total': float(agg['amount']),
        })

