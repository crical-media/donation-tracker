from django.db import models
from django.db.models import Q;
from django.db.models import Sum,Max
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
import mptt.models;

import calendar
import urllib2
from datetime import datetime
from decimal import Decimal
import re;
import pytz;
import cld;

def positive(value):
  if value <  0: raise ValidationError('Value cannot be negative')

def nonzero(value):
  if value == 0: raise ValidationError('Value cannot be zero')

_timezoneChoices = list(map(lambda x: (x,x), pytz.common_timezones));
_currencyChoices = (('USD','US Dollars'),('CAD', 'Canadian Dollars'));

class Event(models.Model):
  short = models.CharField(max_length=64,unique=True)
  name = models.CharField(max_length=128)
  receivername = models.CharField(max_length=128,blank=True,null=False,verbose_name='Receiver Name')
  targetamount = models.DecimalField(decimal_places=2,max_digits=20,validators=[positive,nonzero],verbose_name='Target Amount')
  usepaypalsandbox = models.BooleanField(default=False,verbose_name='Use Paypal Sandbox');
  paypalemail = models.EmailField(max_length=128,null=False,blank=False, verbose_name='Receiver Paypal')
  paypalcurrency = models.CharField(max_length=8,null=False,blank=False,default=_currencyChoices[0][0],choices=_currencyChoices, verbose_name='Currency')
  scheduleid = models.CharField(max_length=128,unique=True,null=True,blank=True, verbose_name='Schedule ID')
  scheduletimezone = models.CharField(max_length=64,blank=True,choices=_timezoneChoices, default='US/Eastern', verbose_name='Schedule Timezone');
  scheduledatetimefield = models.CharField(max_length=128,blank=True, verbose_name='Schedule Datetime')
  schedulegamefield = models.CharField(max_length=128,blank=True, verbose_name='Schdule Game')
  schedulerunnersfield = models.CharField(max_length=128,blank=True, verbose_name='Schedule Runners')
  scheduleestimatefield = models.CharField(max_length=128,blank=True, verbose_name='Schedule Estimate')
  schedulesetupfield = models.CharField(max_length=128,blank=True, verbose_name='Schedule Setup')
  schedulecommentatorsfield = models.CharField(max_length=128,blank=True,verbose_name='Schedule Commentators')
  schedulecommentsfield = models.CharField(max_length=128,blank=True,verbose_name='Schedule Comments')
  date = models.DateField()
  def __unicode__(self):
    return self.name
  def clean(self):
    if self.id and self.id < 1:
      raise ValidationError('Event ID must be positive and non-zero')
    if not re.match('^\w+$', self.short):
      raise ValidationError('Event short name must be a url-safe string');
    if not self.scheduleid:
      self.scheduleid = None;

class Bid(mptt.models.MPTTModel):
  event = models.ForeignKey('Event', verbose_name='Event', null=True, blank=True, related_name='bids');
  speedrun = models.ForeignKey('SpeedRun', verbose_name='Run', null=True, blank=True, related_name='bids');
  parent = mptt.models.TreeForeignKey('self', verbose_name='Parent', null=True, blank=True, related_name='options');
  name = models.CharField(max_length=64);
  state = models.CharField(max_length=32,choices=(('HIDDEN', 'Hidden'), ('OPENED','Opened'), ('CLOSED','Closed')),default='OPENED');
  description = models.TextField(max_length=1024,blank=True);
  goal = models.DecimalField(decimal_places=2,max_digits=20,null=True,blank=True, default=None);
  istarget = models.BooleanField(default=False,verbose_name='Target',help_text="Set this if this bid is a 'target' for donations (bottom level choice or challenge)");
  revealedtime = models.DateTimeField(verbose_name='Revealed Time', null=True, blank=True);
  class Meta:
    unique_together = (('event', 'name', 'speedrun', 'parent',),);
    ordering = ['event__name', 'speedrun__starttime', 'parent__name', 'name'];
    permissions = (
      ('view_hidden', 'Can view hidden bids'),
    )
  class MPTTMeta:
    order_insertion_by = ['name']
  def clean(self):
    # Manually de-normalize speedrun/event/state to help with searching
    if self.parent:
      curr = self.parent;
      while curr.parent != None:
        curr = curr.parent;
      root = curr;
      self.speedrun = root.speedrun;
      self.event = root.event;
      self.state = root.state;
    else:
      for option in self.get_descendants():
        option.speedrun = self.speedrun;
        option.event = self.event;
        option.state = self.state;
        option.save();
    if not self.goal:
      self.goal = None;
    elif self.goal <= Decimal('0.0'):
      raise ValidationError('Goal should be a positive value');
    if self.istarget and self.options.count() != 0:
      raise ValidationError('Targets cannot have children')
    if self.parent and self.parent.istarget:
      raise ValidationError('Cannot set that parent, parent is a target')
    sameName = Bid.objects.filter(speedrun=self.speedrun, event=self.event, parent=self.parent, name__iexact=self.name);
    if sameName.exists():
      if sameName.count() > 1 or sameName[0].id != self.id:
        raise ValidationError('Cannot have a bid under the same event/run/parent with the same name');
    if self.id == None or (sameName.exists() and sameName[0].state == 'HIDDEN' and self.state == 'OPENED'):
      self.revealedtime = datetime.utcnow().replace(tzinfo=pytz.utc);

  def get_event(self):
    if self.speedrun:
      return self.speedrun.event;
    else:
      return self.event;

  def __unicode__(self):
    if self.parent:
      return unicode(self.parent) + ' -- ' + self.name;
    elif self.speedrun:
      return self.speedrun.name  + ' -- ' + self.name;
    else:
      return unicode(self.event) + ' -- ' + self.name;
  def fullname(self):
    return ((self.parent.fullname() + ' -- ') if self.parent else '') + self.name;

class DonationBid(models.Model):
  bid = models.ForeignKey('Bid',related_name='bids')
  donation = models.ForeignKey('Donation', related_name='bids')
  amount = models.DecimalField(decimal_places=2,max_digits=20,validators=[positive,nonzero])
  class Meta:
    verbose_name = 'Donation Bid'
    ordering = [ '-donation__timereceived' ]
  def clean(self):
    if not self.bid.is_leaf_node():
      raise ValidationError('Target bid must be a leaf node');
    self.donation.clean(self);
  def __unicode__(self):
    return unicode(self.bid) + ' -- ' + unicode(self.donation)

class BidSuggestion(models.Model):
  bid = models.ForeignKey('Bid', related_name='suggestions', null=False);
  name = models.CharField(max_length=64, blank=False, null=False, verbose_name="Name");
  class Meta:
    ordering = [ 'name' ];
  def clean(self):
    sameBid = BidSuggestion.objects.filter(Q(name__iexact=self.name) & (Q(bid__event=self.bid.get_event()) | Q(bid__speedrun__event=self.bid.get_event()))); 
    if sameBid.exists():
      if sameBid.count() > 1 or sameBid[0].id != self.id:
        raise ValidationError("Cannot have a bid suggestion with the same name within the same event.");
  def __unicode__(self):
    return self.name + " -- " + unicode(self.bid);

def LatestEvent():
  if Event.objects.all().exists():
    return Event.objects.reverse()[0]
  else:
    return None;

DonorVisibilityChoices = (('FULL', 'Fully Visible'), ('FIRST', 'First Name, Last Initial'), ('ALIAS', 'Alias Only'), ('ANON', 'Anonymous'));

DonationDomainChoices = (('LOCAL', 'Local'), ('CHIPIN', 'ChipIn'), ('PAYPAL', 'PayPal'));

LanguageChoices = (('un', 'Unknown'), ('en', 'English'), ('fr', 'French'), ('de', 'German'));

class Donation(models.Model):
  donor = models.ForeignKey('Donor', blank=True, null=True)
  event = models.ForeignKey('Event', default=LatestEvent)
  domain = models.CharField(max_length=255,default='LOCAL',choices=DonationDomainChoices);
  domainId = models.CharField(max_length=160,unique=True,editable=False,blank=True)
  transactionstate = models.CharField(max_length=64, default='PENDING', choices=(('PENDING', 'Pending'), ('COMPLETED', 'Completed'), ('CANCELLED', 'Cancelled'), ('FLAGGED', 'Flagged')))
  bidstate = models.CharField(max_length=255,default='PENDING',choices=(('PENDING', 'Pending'), ('IGNORED', 'Ignored'), ('PROCESSED', 'Processed'), ('FLAGGED', 'Flagged')),verbose_name='Bid State')
  readstate = models.CharField(max_length=255,default='PENDING',choices=(('PENDING', 'Pending'), ('READY', 'Ready to Read'), ('IGNORED', 'Ignored'), ('READ', 'Read'), ('FLAGGED', 'Flagged')),verbose_name='Read State')
  commentstate = models.CharField(max_length=255,default='ABSENT',choices=(('ABSENT', 'Absent'), ('PENDING', 'Pending'), ('DENIED', 'Denied'), ('APPROVED', 'Approved'), ('FLAGGED', 'Flagged')),verbose_name='Comment State')
  amount = models.DecimalField(decimal_places=2,max_digits=20,validators=[positive,nonzero],verbose_name='Donation Amount')
  fee = models.DecimalField(decimal_places=2,max_digits=20,default=Decimal('0.00'),validators=[positive],verbose_name='Donation Fee')
  currency = models.CharField(max_length=8,null=False,blank=False,choices=_currencyChoices,verbose_name='Currency')
  timereceived = models.DateTimeField(verbose_name='Time Received')
  comment = models.TextField(blank=True,verbose_name='Comment')
  modcomment = models.TextField(blank=True,verbose_name='Moderator Comment')
  # Specifies if this donation is a 'test' donation, i.e. generated by a sandbox test, and should not be counted
  testdonation = models.BooleanField(default=False);
  requestedvisibility = models.CharField(max_length=32, null=False, blank=False, default='CURR', choices=(('CURR', 'Use Existing (Anonymous if not set)'),) + DonorVisibilityChoices, verbose_name='Requested Visibility');
  requestedalias = models.CharField(max_length=32, null=True, blank=True, verbose_name='Requested Alias');
  requestedemail = models.EmailField(max_length=128, null=True, blank=True, verbose_name='Requested Contact Email');
  commentlanguage = models.CharField(max_length=32, null=False, blank=False, default='un', choices=LanguageChoices, verbose_name='Comment Language');
  class Meta:
    permissions = (
      ('view_full_list', 'Can view full donation list'),
      ('view_comments', 'Can view all comments'),
      ('view_pending', 'Can view pending doantions'),
      ('view_test', 'Can view test donations'),
    )
    get_latest_by = 'timereceived'
    ordering = [ '-timereceived' ]

  def bid_total(self):
    return reduce(lambda a, b: a + b, map(lambda b: b.amount, self.bids.all()), Decimal('0.00'));

  def clean(self,bid=None):
    super(Donation,self).clean()
    if not self.donor and self.transactionstate != 'PENDING':
      raise ValidationError('Donation must have a donor when in a non-pending state');
    if not self.domainId and self.donor:
      self.domainId = str(calendar.timegm(self.timereceived.timetuple())) + self.donor.email
    bids = set()
    if bid: 
      bids |= set([bid])
    bids |= set()|set(self.bids.all())
    bids = map(lambda b: b.amount,bids)
    bidtotal = reduce(lambda a,b: a+b,bids,Decimal('0'))
    if self.amount and bidtotal > self.amount:
      raise ValidationError('Bid total is greater than donation amount: %s > %s' % (bidtotal,self.amount))
    
    tickets = self.tickets.all();
    print(tickets);
    ticketTotal = reduce(lambda a,b: a+b, map(lambda b: b.amount, tickets), Decimal('0'));
    if self.amount and ticketTotal > self.amount:
      raise ValidationError('Prize ticket total is greater than donation amount: %s > %s' % (ticketTotal,self.amount))
    
    if self.comment:
      if self.commentlanguage == 'un' or self.commentlanguage == None:
        detectedLangName, detectedLangCode, isReliable, textBytesFound, details = cld.detect(self.comment.encode('utf-8'), hintLanguageCode ='en');
        if detectedLangCode in map(lambda x: x[0], LanguageChoices):
          self.commentlanguage = detectedLangCode;
        else:
          self.commentlanguage = 'un';
    else:
      self.commentlanguage = 'un';
  def __unicode__(self):
    return unicode(self.donor) + ' (' + unicode(self.amount) + ') (' + unicode(self.timereceived) + ')'

class Donor(models.Model):
  email = models.EmailField(max_length=128,unique=True,verbose_name='Contact Email')
  alias = models.CharField(max_length=32,unique=True,null=True,blank=True)
  firstname = models.CharField(max_length=32,blank=True,verbose_name='First Name')
  lastname = models.CharField(max_length=32,blank=True,verbose_name='Last Name')
  visibility = models.CharField(max_length=32, null=False, blank=False, default='FIRST', choices=DonorVisibilityChoices);

  # Address information, yay!
  addresscity = models.CharField(max_length=128,blank=True,null=False,verbose_name='City');
  addressstreet = models.CharField(max_length=128,blank=True,null=False,verbose_name='Street/P.O. Box');
  addressstate = models.CharField(max_length=128,blank=True,null=False,verbose_name='State/Province');
  addresszip = models.CharField(max_length=128,blank=True,null=False,verbose_name='Zip/Postal Code');
  addresscountry = models.CharField(max_length=128,blank=True,null=False,verbose_name='Country');

  # Donor specific info
  paypalemail = models.EmailField(max_length=128,unique=True,null=True,blank=True,verbose_name='Paypal Email')

  # Runner info
  runneryoutube = models.CharField(max_length=128,unique=True,blank=True,null=True,verbose_name='Youtube Account');
  runnertwitch = models.CharField(max_length=128,unique=True,blank=True,null=True,verbose_name='Twitch Account');
  runnertwitter = models.CharField(max_length=128,unique=True,blank=True,null=True,verbose_name='Twitter Account');

  # Prize contributor info
  prizecontributoremail = models.EmailField(max_length=128,unique=True,blank=True,null=True,verbose_name='Contact Email');
  prizecontributorwebsite = models.URLField(blank=True,null=True,verbose_name='Personal Website');

  class Meta:
    permissions = (
      ('view_usernames', 'Can view full usernames'),
      ('view_emails', 'Can view email addresses'),
    )
    ordering = ['lastname', 'firstname', 'email']
  def clean(self):
    # an empty value means a null value
    if not self.alias:
      self.alias = None;
    if not self.paypalemail:
      self.paypalemail = None;
    if self.visibility == 'ALIAS' and not self.alias:
      raise ValidationError("Cannot set Donor visibility to 'Alias Only' without an alias");
    if not self.runneryoutube:
      self.runneryoutube = None;
    if not self.runnertwitch:
      self.runnertwitch = None;
    if not self.runnertwitter:
      self.runnertwitter = None;
    if not self.prizecontributoremail:
      self.prizecontributoremail = None;
    if not self.prizecontributorwebsite:
      self.prizecontributorwebsite = None;
  def visible_name(self):
    if self.visibility == 'ANON':
      return u'(Anonymous)'
    elif self.visibility == 'ALIAS':
      return self.alias;
    last_name,first_name = self.lastname,self.firstname
    if not last_name and not first_name:
      return u'(No Name)' if self.alias == None else self.alias;
    if self.visibility == 'FIRST':
      last_name = last_name[:1] + u'...'
    return last_name + u', ' + first_name + (u'' if self.alias == None else u' (' + self.alias + u')');
  def full(self):
    return unicode(self.email) + u' (' + unicode(self) + u')'
  def __unicode__(self):
    if not self.lastname and not self.firstname:
      return self.alias or u'(No Name)'
    ret = unicode(self.lastname) + ', ' + unicode(self.firstname)
    if self.alias:
      ret += u' (' + unicode(self.alias) + u')'
    return ret

class PrizeTicket(models.Model):
  prize = models.ForeignKey('Prize',related_name='tickets');
  donation = models.ForeignKey('Donation', related_name='tickets');
  amount = models.DecimalField(decimal_places=2,max_digits=20,validators=[positive,nonzero]);
  class Meta:
    verbose_name = 'Prize Ticket';
    ordering = [ '-donation__timereceived' ];
  def clean(self):
    self.donation.clean(self);
  def __unicode__(self):
    return unicode(self.prize) + ' -- ' + unicode(self.donation);

class PrizeWinner(models.Model):
  winner = models.ForeignKey('Donor', null=False, blank=False);
  prize = models.ForeignKey('Prize', null=False, blank=False);
  emailsent = models.BooleanField(default=False, verbose_name='Email Sent');
  class Meta:
    unique_together = ( 'prize', 'winner', );
  def validate_unique(self, **kwargs):
    if 'winner' not in kwargs and 'prize' not in kwargs and self.prize.category != None:
      for prizeWon in PrizeWinner.objects.filter(prize__category=self.prize.category, winner=self.winner, prize__event=self.prize.event):
        if prizeWon.id != self.id:
          raise ValidationError('Category, winner, and prize event must be unique together');
        
class Prize(models.Model):
  name = models.CharField(max_length=64,unique=True)
  category = models.ForeignKey('PrizeCategory',null=True,blank=True)
  sortkey = models.IntegerField(default=0,db_index=True)
  image = models.URLField(max_length=1024,null=True,blank=True)
  description = models.TextField(max_length=1024,null=True,blank=True)
  minimumbid = models.DecimalField(decimal_places=2,max_digits=20,default=Decimal('5.0'),verbose_name='Minimum Bid',validators=[positive,nonzero])
  maximumbid = models.DecimalField(decimal_places=2,max_digits=20,null=True,blank=True,default=Decimal('5.0'),verbose_name='Maximum Bid',validators=[positive,nonzero])
  sumdonations = models.BooleanField(verbose_name='Sum Donations')
  randomdraw = models.BooleanField(default=True,verbose_name='Random Draw')
  ticketdraw = models.BooleanField(default=False,verbose_name='Ticket Draw');
  event = models.ForeignKey('Event', default=LatestEvent)
  startrun = models.ForeignKey('SpeedRun',related_name='prize_start',null=True,blank=True,verbose_name='Start Run')
  endrun = models.ForeignKey('SpeedRun',related_name='prize_end',null=True,blank=True,verbose_name='End Run')
  starttime = models.DateTimeField(null=True,blank=True,verbose_name='Start Time')
  endtime = models.DateTimeField(null=True,blank=True,verbose_name='End Time')
  winners = models.ManyToManyField('Donor', related_name='prizeswon', blank=True, null=True, through='PrizeWinner')
  maxwinners = models.IntegerField(default=1, verbose_name='Max Winners', validators=[positive, nonzero], blank=False, null=False);
  deprecated_provided = models.CharField(max_length=64,blank=True,verbose_name='*DEPRECATED* Provided By') # Deprecated
  contributors = models.ManyToManyField('Donor', related_name='prizescontributed', blank=True, null=True);
  class Meta:
    ordering = [ 'event__date', 'startrun__starttime', 'starttime', 'name' ]
  def __unicode__(self):
    return unicode(self.name)
  def clean(self):
    if (not self.startrun) != (not self.endrun):
      raise ValidationError('Must have both Start Run and End Run set, or neither')
    if self.startrun and self.event != self.startrun.event:
      raise ValidationError('Prize Event must be the same as Start Run Event')
    if self.endrun and self.event != self.endrun.event:
      raise ValidationError('Prize Event must be the same as End Run Event')
    if self.startrun and self.startrun.sortkey > self.endrun.sortkey:
      raise ValidationError('Start Run must have a lesser sortkey than End Run')
    if (not self.starttime) != (not self.endtime):
      raise ValidationError('Must have both Start Run and End Run set, or neither')
    if self.starttime and self.starttime > self.endtime:
      raise ValidationError('Prize Start Time must be later than End Time')
    if self.startrun and self.starttime:
      raise ValidationError('Cannot have both Start/End Run and Start/End Time set')   
    if self.maximumbid != None and self.maximumbid < self.minimumbid:
      raise ValidationError('Maximum Bid cannot be lower than Minimum Bid')
    if not self.sumdonations and self.maximumbid != self.minimumbid:
      raise ValidationError('Maximum Bid cannot differ from Minimum Bid if Sum Donations is not checked')
  def eligible_donors(self):
    qs = Donation.objects.filter(event=self.event,transactionstate='COMPLETED').select_related('donor')
    qs = qs.exclude(donor__prizeswon__category=self.category, donor__prizeswon__event=self.event);
    if self.ticketdraw:
      qs = qs.filter(tickets__prize=self).annotate(ticketAmount=Sum('tickets__amount'));
    elif self.has_draw_time():
      qs = qs.filter(timereceived__gte=self.start_draw_time(),timereceived__lte=self.end_draw_time());
    donors = {}
    for d in qs:
      if self.sumdonations:
        donors.setdefault(d.donor, Decimal('0.0'))
        if self.ticketdraw:
          donors[d.donor] += d.ticketAmount;
        else:
          donors[d.donor] += d.amount
      else:
        if self.ticketdraw:
          donors[d.donor] = max(d.ticketAmount,donors.get(d.donor,Decimal('0.0')))
        else:
          donors[d.donor] = max(d.amount,donors.get(d.donor,Decimal('0.0')))
    if not donors:
      return []
    elif self.randomdraw:
      def weight(mn,mx,a):
        if a < mn: return 0.0
        if mx != None and a > mx: return float(mx/mn)
        return float(a/mn)
      return sorted(filter(lambda d: d['weight'] >= 1.0,map(lambda d: {'donor':d[0].id,'amount':d[1],'weight':weight(self.minimumbid,self.maximumbid,d[1])}, donors.items())),key=lambda d: d['donor'])
    else:
      m = max(donors.items(), key=lambda d: d[1])
      return [{'donor':m[0].id,'amount':m[1],'weight':1.0}]
  def games_based_drawing(self):
    return self.startrun and self.endrun;
  def games_range(self):
    if self.games_based_drawing():
      return SpeedRun.objects.filter(event=self.event, starttime__gte=self.startrun.starttime, endtime__lte=self.endrun.endtime);
    else:
      return SpeedRun.objects.none();
  def has_draw_time(self):
    return self.start_draw_time() and self.end_draw_time();
  def start_draw_time(self):
    if self.startrun:
      return self.startrun.starttime.replace(tzinfo=pytz.utc);
    elif self.starttime:
      return self.starttime.replace(tzinfo=pytz.utc);
    else:
      return None;
  def end_draw_time(self):
    if self.endrun:
      return self.endrun.endtime.replace(tzinfo=pytz.utc);
    elif self.endtime:
      return self.endtime.replace(tzinfo=pytz.utc);
    else:
      return None;
  def maxed_winners(self):
    return self.maxwinners == self.winners.count();
  def get_winner(self):
    if self.maxwinners == 1:
      if self.winners.exists():
        return self.winners.all()[0];
      else:
        return None;
    else:
      raise Exception("Cannot get single winner for multi-winner prize");

class PrizeCategory(models.Model):
  name = models.CharField(max_length=64,unique=True)
  class Meta:
    verbose_name = 'Prize Category'
    verbose_name_plural = 'Prize Categories'
  def __unicode__(self):
    return self.name

class SpeedRun(models.Model):
  name = models.CharField(max_length=64)
  deprecated_runners = models.CharField(max_length=1024,blank=True,verbose_name='*DEPRECATED* Runners') # This field is now deprecated, we should eventually set up a way to migrate the old set-up to use the donor links
  sortkey = models.IntegerField(db_index=True,verbose_name='Sort Key')
  description = models.TextField(max_length=1024,blank=True)
  event = models.ForeignKey('Event', default=LatestEvent)
  starttime = models.DateTimeField(verbose_name='Start Time')
  endtime = models.DateTimeField(verbose_name='End Time')
  runners = models.ManyToManyField('Donor', blank=True, null=True);
  class Meta:
    verbose_name = 'Speed Run';
    unique_together = ( 'name','event' );
    ordering = [ 'event__date', 'starttime' ];
  def __unicode__(self):
    return u'%s (%s)' % (self.name,self.event)

class UserProfile(models.Model):
  user = models.ForeignKey(User, unique=True)
  prepend = models.CharField('Template Prepend', max_length=64,blank=True)
  class Meta:
    verbose_name = 'User Profile'
    permissions = (
      ('show_rendertime', 'Can view page render times'),
      ('show_queries', 'Can view database queries'),
      ('sync_schedule', 'Can sync the schedule'),
      ('can_search', 'Can use search url'),
    )
  def __unicode__(self):
    return unicode(self.user)

