from django.urls import path, include, re_path

from .views import public, api, donateviews, user, auth, eventviews, feedviews

app_name = 'tracker'
urlpatterns = [
    path('i18n', include('django.conf.urls.i18n')),

    # Use regex paths for some of these when they have optional fields.
    re_path(r'^bids/(?P<event>\w+|)$', public.bidindex, name='bidindex'),
    path('bid/<int:id>', public.bid, name='bid'),
    re_path(r'^donors/(?P<event>\w+|)$', public.donorindex, name='donorindex'),
    path('donor/<int:id>', public.donor, name='donor'),
    re_path(r'^donor/(?P<id>-?\d+)/(?P<event>\w*)$', public.donor, name='donor'),
    re_path(r'^donations/(?P<event>\w+|)$', public.donationindex, name='donationindex'),
    path('donation/<int:id>', public.donation, name='donation'),
    re_path(r'^runs/(?P<event>\w+|)$', public.runindex, name='runindex'),
    path('run/<int:id>', public.run, name='run'),
    re_path(r'^prizes/(?P<event>\w+|)$', public.prizeindex, name='prizeindex'),
    path('prize/<int:id>', public.prize, name='prize'),
    re_path(r'^events/$', public.eventlist, name='eventlist'),
    re_path(r'^index/(?P<event>\w+|)$', public.index, name='index'),
    # unfortunately, using the 'word' variant here clashes with the admin site (not to mention any unparameterized urls), so I guess its going to have to be this way for now.  I guess that ideally, one would only use the 'index' url, and redirect to it as neccessary).
    re_path(r'^(?P<event>\d+|)$', public.index),

    path('donate/<slug:event>', donateviews.donate, name='donate'),
    path('paypal_return', donateviews.paypal_return, name='paypal_return'),
    path('paypal_cancel', donateviews.paypal_cancel, name='paypal_cancel'),
    path('ipn', donateviews.ipn, name='ipn'),

    path('prize_donors', api.prize_donors),
    path('draw_prize', api.draw_prize),
    path('search', api.search),
    path('add', api.add),
    path('edit', api.edit),
    path('delete', api.delete),
    path('command', api.command),
    path('me', api.me),
    path('api/v1', api.api_v1),
    path('api/v1/search', api.search),
    path('api/v1/add', api.add),
    path('api/v1/edit', api.edit),
    path('api/v1/delete', api.delete),
    path('api/v1/command', api.command),
    path('api/v1/me', api.me),
    path('api/v2/', include('tracker.api.urls')),

    # AJAX calls
    path('horaro_schedule_cols/<slug:slug>', eventviews.HoraroScheduleColsView.as_view(), name='horaro_schedule_cols'),

    # Data feed calls for tickers
    path('feed/upcoming_runs/<slug:event>', feedviews.UpcomingRunsView.as_view(), name='feed_upcoming_runs'),
    path('feed/upcoming_bids/<slug:event>', feedviews.UpcomingBidsView.as_view(), name='feed_upcoming_bids'),
    path('feed/current_donations/<slug:event>', feedviews.CurrentDonationsView.as_view(), name='feed_current_donations'),
    path('feed/donations/<slug:event>', feedviews.RecentDonationsView.as_view(), name='feed_recent_donations'),

    path('user/index', user.user_index, name='user_index'),
    path('user/user_prize/<int:prize>', user.user_prize, name='user_prize'),
    path('user/prize_winner/<int:prize_win>', user.prize_winner, name='prize_winner'),
    path('user/submit_prize/<slug:event>', user.submit_prize, name='submit_prize'),

    path('user/login', auth.login, name='login'),
    path('user/logout', auth.logout, name='logout'),
    path('user/password_reset', auth.password_reset, name='password_reset'),
    path('user/password_reset_done', auth.password_reset_done, name='password_reset_done'),
    path('user/password_reset_confirm', auth.password_reset_confirm, name='password_reset_confirm'),
    path('user/password_reset_complete', auth.password_reset_complete, name='password_reset_complete'),
    path('user/password_change', auth.password_change, name='password_change'),
    path('user/password_change_done', auth.password_change_done, name='password_change_done'),
    path('user/register', auth.register, name='register'),
    path('user/confirm_registration', auth.confirm_registration, name='confirm_registration'),
]

