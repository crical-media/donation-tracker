import csv
from datetime import timedelta
from decimal import Decimal

from django.contrib import admin
from django.urls import re_path
from django.contrib import messages
from django.contrib.admin import register
from django.contrib.auth.decorators import permission_required
from django.contrib.contenttypes.models import ContentType
from django.db.models import Sum
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, redirect
from django.urls import reverse
from tracker.admin.util import latest_event_id

import tracker.models.fields
from tracker import models, search_filters, forms, viewutil
from .filters import RunListFilter
from .inlines import BidInline, EventBidInline

import tracker.horaro as horaro

@register(models.Event)
class EventAdmin(admin.ModelAdmin):
    search_fields = ('short', 'name')
    inlines = [EventBidInline]
    list_display = ['name', 'locked', 'allow_donations']
    list_editable = ['locked', 'allow_donations']
    readonly_fields = ['scheduleid']
    autocomplete_fields = ('allowed_prize_countries', 'disallowed_prize_regions', 'prizecoordinator')
    fieldsets = [
        (
            None,
            {
                'fields': [
                    'short',
                    'name',
                    'hashtag',
                    'receivername',
                    'targetamount',
                    'use_one_step_screening',
                    'minimumdonation',
                    'auto_approve_threshold',
                    'datetime',
                    'timezone',
                    'locked',
                    'allow_donations',
                ]
            },
        ),
        (
            'Horaro Schedule',
            {
                'classes': ['collapse'],
                'fields': ['horaro_id',  'horaro_game_col', 'horaro_category_col',
                            'horaro_runners_col'],
            }
        ),
        (
            'Paypal',
            {
                'classes': ['collapse'],
                'fields': ['paypalemail', 'paypalcurrency', 'paypalimgurl'],
            },
        ),
        (
            'Donation Autoreply',
            {
                'classes': ['collapse',],
                'fields': [
                    'donationemailsender',
                    'donationemailtemplate',
                    'pendingdonationemailtemplate',
                ],
            },
        ),
        (
            'Prize Management',
            {
                'classes': ['collapse',],
                'fields': [
                    'prize_accept_deadline_delta',
                    'prizecoordinator',
                    'allowed_prize_countries',
                    'disallowed_prize_regions',
                    'prizecontributoremailtemplate',
                    'prizewinneremailtemplate',
                    'prizewinneracceptemailtemplate',
                    'prizeshippedemailtemplate',
                ],
            },
        ),
        ('Google Document', {'classes': ['collapse'], 'fields': ['scheduleid']}),
    ]

    def get_urls(self):
        return super(EventAdmin, self).get_urls() + [
            re_path(
                'select_event',
                self.admin_site.admin_view(self.select_event),
                name='select_event',
            ),
        ]

    def select_event(self, request):
        current = viewutil.get_selected_event(request)
        if request.method == 'POST':
            form = forms.EventFilterForm(data=request.POST)
            if form.is_valid():
                viewutil.set_selected_event(request, form.cleaned_data['event'])
                return redirect('admin:index')
        else:
            form = forms.EventFilterForm(**{'event': current})
        return render(request, 'admin/select_event.html', {'form': form})

    def donor_report(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request, 'Select exactly one event.', level=messages.ERROR,
            )
            return
        event = queryset.first()
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            'attachment; filename="donor-report-%s.csv"' % event.short
        )
        writer = csv.writer(response)
        writer.writerow(['Name', 'Donation Sum', 'Donation Count'])
        anon = tracker.models.Donation.objects.filter(
            donor__visibility='ANON', transactionstate='COMPLETED', event=event
        )
        writer.writerow(
            [
                'All Anonymous Donations',
                anon.aggregate(Sum('amount'))['amount__sum'].quantize(Decimal('1.00')),
                anon.count(),
            ]
        )
        donors = (
            tracker.models.DonorCache.objects.filter(event=event)
            .exclude(donor__visibility='ANON')
            .select_related('donor')
            .iterator()
        )
        for d in donors:
            writer.writerow([d.visible_name(), d.donation_total, d.donation_count])
        return response

    donor_report.short_description = 'Export donor CSV'

    def run_report(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request, 'Select exactly one event.', level=messages.ERROR,
            )
            return
        event = queryset.first()
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            'attachment; filename="run-report-%s.csv"' % event.short
        )
        writer = csv.writer(response)
        writer.writerow(
            ['Run', 'Event', 'Start Time', 'End Time', 'Runners', 'Runner Twitters']
        )
        runs = (
            tracker.models.SpeedRun.objects.filter(event=event)
            .exclude(order=None)
            .select_related('event')
            .prefetch_related('runners')
        )
        for r in runs:
            writer.writerow(
                [
                    str(r),
                    r.event.short,
                    r.starttime.astimezone(r.event.timezone).isoformat(),
                    r.endtime.astimezone(r.event.timezone).isoformat(),
                    ','.join(str(ru) for ru in r.runners.all()),
                    ','.join(ru.twitter for ru in r.runners.all() if ru.twitter),
                ]
            )
        return response

    run_report.short_description = 'Export run CSV'

    def donation_report(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request, 'Select exactly one event.', level=messages.ERROR,
            )
            return
        event = queryset.first()
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            'attachment; filename="donation-report-%s.csv"' % event.short
        )
        writer = csv.writer(response)
        writer.writerow(['Donor', 'Event', 'Amount', 'Time Received'])
        donations = (
            tracker.models.Donation.objects.filter(
                transactionstate='COMPLETED', event=event
            )
            .select_related('donor', 'event')
            .iterator()
        )
        for d in donations:
            writer.writerow(
                [
                    d.donor.visible_name(),
                    d.event.short,
                    d.amount,
                    d.timereceived.astimezone(d.event.timezone).isoformat(),
                ]
            )
        return response

    donation_report.short_description = 'Export donation CSV'

    def bid_report(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request, 'Select exactly one event.', level=messages.ERROR,
            )
            return
        event = queryset.first()
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            'attachment; filename="bid-report-%s.csv"' % event.short
        )
        writer = csv.writer(response)
        writer.writerow(['Id', 'Bid', 'Event', 'Target', 'Goal', 'Amount', 'Count'])
        bids = (
            tracker.models.Bid.objects.filter(
                state__in=['CLOSED', 'OPENED'], event=event
            )
            .order_by('event__datetime', 'speedrun__order', 'parent__name', '-total')
            .select_related('event', 'speedrun', 'parent')
            .iterator()
        )
        for b in bids:
            writer.writerow(
                [b.id, str(b), b.event.short, b.istarget, b.goal, b.total, b.count]
            )
        return response

    bid_report.short_description = 'Export bid CSV'

    def donationbid_report(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request, 'Select exactly one event.', level=messages.ERROR,
            )
            return
        event = queryset.first()
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            'attachment; filename="donationbid-report-%s.csv"' % event.short
        )
        writer = csv.writer(response)
        writer.writerow(['Bid', 'Amount', 'Time'])
        donation_bids = (
            tracker.models.DonationBid.objects.filter(
                bid__state__in=['CLOSED', 'OPENED'],
                bid__event=event,
                donation__transactionstate='COMPLETED',
            )
            .order_by('donation__timereceived')
            .select_related('donation')
            .iterator()
        )
        for b in donation_bids:
            writer.writerow([b.bid_id, b.amount, b.donation.timereceived])
        return response

    donationbid_report.short_description = 'Export donation bid CSV'

    def prize_report(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request, 'Select exactly one event.', level=messages.ERROR,
            )
            return
        event = queryset.first()
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            'attachment; filename="prize-report-%s.csv"' % event.short
        )
        writer = csv.writer(response)
        writer.writerow(
            [
                'Event',
                'Name',
                'Eligible Donors',
                'Exact Donors',
                'Start Time',
                'End Time',
            ]
        )
        prizes = tracker.models.Prize.objects.filter(
            state='ACCEPTED', event=event
        ).iterator()
        for p in prizes:
            eligible = p.eligible_donors()
            writer.writerow(
                [
                    p.event.short,
                    p.name,
                    len(eligible),
                    len([d for d in eligible if d['amount'] == p.minimumbid]),
                    p.start_draw_time(),
                    p.end_draw_time(),
                ]
            )
        return response

    prize_report.short_description = 'Export prize CSV'

    def email_report(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request, 'Select exactly one event.', level=messages.ERROR,
            )
            return
        event = queryset.first()
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            'attachment; filename="email-report-%s.csv"' % event.short
        )
        writer = csv.writer(response)
        writer.writerow(['Email', 'Name', 'Anonymous', 'Donation Sum', 'Country'])
        donors = (
            tracker.models.DonorCache.objects.filter(
                event=event, donor__solicitemail='OPTIN',
            )
            .select_related('donor')
            .iterator()
        )
        for d in donors:
            if d.firstname:
                if d.lastname:
                    name = u'%s, %s' % (d.lastname, d.firstname)
                else:
                    name = d.firstname
            else:
                name = '(No Name Supplied)'
            writer.writerow(
                [
                    d.email,
                    name,
                    d.visibility == 'ANON',
                    d.donation_total,
                    d.addresscountry,
                ]
            )
        return response

    email_report.short_description = 'Export email opt-in CSV'

    def merge_horaro_schedule(self, request, queryset):
        """Merge run schedule from Horaro API."""
        if len(queryset) != 1:
            self.message_user(request, "Please select only a single event for Horaro merge", level=messages.ERROR)
            return

        # Get content type for log entries.
        ct = ContentType.objects.get_for_model(tracker.models.Event)

        num_runs = 0
        for event in queryset:
            try:
                with transaction.atomic():
                    num_runs = horaro.merge_event_schedule(event)
                    msg = 'Merged Horaro schedule for event {} - {} runs'.format(event, num_runs)
                    admin.models.LogEntry.objects.log_action(user_id=request.user.id, content_type_id=ct.pk, object_id=event.pk,
                                                   object_repr=str(event), action_flag=admin.models.CHANGE,
                                                   change_message=msg)
            except horaro.HoraroError as e:
                self.message_user(request, "Can't merge Horaro schedule - {}".format(e), level=messages.ERROR)
        else:
            self.message_user(request, "%d runs merged for %s." % (num_runs, event.name), level=messages.SUCCESS)

    merge_horaro_schedule.short_description = "Merge Horaro schedule for a single event (do this once every 24 hours)"

    actions = [
        donor_report,
        run_report,
        donation_report,
        bid_report,
        donationbid_report,
        prize_report,
        email_report,
        merge_horaro_schedule
    ]


@register(models.PostbackURL)
class PostbackURLAdmin(admin.ModelAdmin):
    search_fields = ('url',)
    list_filter = ('event',)
    list_display = ('url', 'event')
    autocomplete_fields = ('event',)
    fieldsets = [(None, {'fields': ['event', 'url']})]

    def get_queryset(self, request):
        event = viewutil.get_selected_event(request)
        if event:
            return models.PostbackURL.objects.filter(event=event)
        else:
            return models.PostbackURL.objects.all()
    
    def get_changeform_initial_data(self, request):
        return super().get_changeform_initial_data(request) | {
            "event": latest_event_id
        }

@register(models.Runner)
class RunnerAdmin(admin.ModelAdmin):
    search_fields = [
        'name',
        'stream',
        'twitter',
        'youtube',
        'platform',
        'pronouns',
        'donor__alias',
        'donor__firstname',
        'donor__lastname',
        'donor__email',
    ]
    list_display = (
        'name',
        'stream',
        'twitter',
        'youtube',
        'platform',
        'pronouns',
        'donor',
    )
    autocomplete_fields = ('donor',)
    fieldsets = [
        (
            None,
            {
                'fields': (
                    'name',
                    'stream',
                    'twitter',
                    'youtube',
                    'platform',
                    'pronouns',
                    'donor',
                )
            },
        ),
    ]


@register(models.SpeedRun)
class SpeedRunAdmin(admin.ModelAdmin):
    search_fields = [
        'name',
        'description',
        'runners__name',
    ]
    list_filter = ['event', RunListFilter]
    inlines = [BidInline]
    list_display = (
        'name',
        'category',
        'description',
        'deprecated_runners',
        'starttime',
        'run_time',
        'setup_time',
    )
    autocomplete_fields = ('event', 'runners')
    fieldsets = [
        (
            None,
            {
                'fields': (
                    'name',
                    'display_name',
                    'twitch_name',
                    'category',
                    'console',
                    'release_year',
                    'description',
                    'event',
                    'order',
                    'starttime',
                    'run_time',
                    'setup_time',
                    'deprecated_runners',
                    'runners',
                    'coop',
                    'tech_notes',
                )
            },
        ),
    ]
    readonly_fields = ('deprecated_runners', 'starttime')
    actions = ['start_run']

    def start_run(self, request, runs):
        if len(runs) != 1:
            self.message_user(request, 'Pick exactly one run.', level=messages.ERROR)
        elif not runs[0].order:
            self.message_user(request, 'Run has no order.', level=messages.ERROR)
        elif runs[0].order == 1:
            self.message_user(request, 'Run is first run.', level=messages.ERROR)
        else:
            return HttpResponseRedirect(reverse('admin:start_run', args=(runs[0].id,)))

    @staticmethod
    @permission_required('tracker.change_speedrun')
    def start_run_view(request, run):
        run = models.SpeedRun.objects.get(id=run)
        prev = models.SpeedRun.objects.filter(
            event=run.event, order__lt=run.order
        ).last()
        form = StartRunForm(
            data=request.POST if request.method == 'POST' else None,
            initial={'run_time': prev.run_time, 'start_time': run.starttime},
        )
        if form.is_valid():
            rt = tracker.models.fields.TimestampField.time_string_to_int(
                form.cleaned_data['run_time']
            )
            endtime = prev.starttime + timedelta(milliseconds=rt)
            if form.cleaned_data['start_time'] < endtime:
                return HttpResponse(
                    'Entered data would cause previous run to end after current run started',
                    status=400,
                    content_type='text/plain',
                )
            prev.run_time = form.cleaned_data['run_time']
            prev.setup_time = str(form.cleaned_data['start_time'] - endtime)
            prev.save()
            messages.info(request, 'Previous run time set to %s' % prev.run_time)
            messages.info(request, 'Previous setup time set to %s' % prev.setup_time)
            run.refresh_from_db()
            messages.info(request, 'Current start time is %s' % run.starttime)
            return HttpResponseRedirect(
                reverse('admin:tracker_speedrun_changelist')
                + '?event=%d' % run.event_id
            )
        return render(
            request,
            'admin/generic_form.html',
            {
                'site_header': 'Donation Tracker',
                'title': 'Set start time for %s' % run,
                'breadcrumbs': (
                    (
                        reverse('admin:app_list', kwargs=dict(app_label='tracker')),
                        'Tracker',
                    ),
                    (reverse('admin:tracker_speedrun_changelist'), 'Speedruns'),
                    (None, 'Start Run'),
                ),
                'form': form,
                'action': request.path,
            },
        )

    def get_queryset(self, request):
        event = viewutil.get_selected_event(request)
        params = {}
        if not request.user.has_perm('tracker.can_edit_locked_events'):
            params['locked'] = False
        if event:
            params['event'] = event.id
        return search_filters.run_model_query('run', params, user=request.user)

    def get_urls(self):
        return super(SpeedRunAdmin, self).get_urls() + [
            re_path(
                r'start_run/(?P<run>\d+)',
                self.admin_site.admin_view(self.start_run_view),
                name='start_run',
            ),
        ]
    
    def get_changeform_initial_data(self, request):
        return super().get_changeform_initial_data(request) | {
            "event": latest_event_id
        }
