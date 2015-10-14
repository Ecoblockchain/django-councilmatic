from django.shortcuts import render, redirect
from django.http import Http404
from django.conf import settings
from django.views.generic import TemplateView, ListView, DetailView
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Max, Min
from .models import Person, Bill, Organization, Action, Event, Post
from haystack.forms import FacetedSearchForm
from datetime import date, timedelta, datetime
import itertools
from operator import attrgetter

import pytz

app_timezone = pytz.timezone(settings.TIME_ZONE)

class CouncilmaticSearchForm(FacetedSearchForm):
    
    def __init__(self, *args, **kwargs):
        self.load_all = True

        super(CouncilmaticSearchForm, self).__init__(*args, **kwargs)

    def no_query_found(self):
        return self.searchqueryset.all()

def city_context(request):
    return {
        'SITE_META': getattr(settings, 'SITE_META', None),
        'CITY_COUNCIL_NAME': getattr(settings, 'CITY_COUNCIL_NAME', None),
        'CITY_NAME': getattr(settings, 'CITY_NAME', None),
        'CITY_NAME_SHORT': getattr(settings, 'CITY_NAME_SHORT', None),
        'SEARCH_PLACEHOLDER_TEXT': getattr(settings,'SEARCH_PLACEHOLDER_TEXT', None),
        'LEGISLATION_TYPE_DESCRIPTIONS': getattr(settings,'LEGISLATION_TYPE_DESCRIPTIONS', None),
        'LEGISTAR_URL': getattr(settings,'LEGISTAR_URL', None),
    }

class IndexView(TemplateView):
     
    template_name = 'councilmatic_core/index.html'
    bill_model = Bill
    event_model = Event

    def get_context_data(self, **kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        
        some_time_ago = date.today() + timedelta(days=-100)
        
        recent_legislation = self.bill_model.objects\
                                 .exclude(last_action_date=None)\
                                 .filter(last_action_date__gt=some_time_ago)\
                                 .order_by('-last_action_date')
        
        recently_passed = [l for l in recent_legislation \
                               if l.inferred_status == 'Passed' \
                                   and l.bill_type == 'Introduction'][:3]

        upcoming_meetings = list(self.event_model.upcoming_committee_meetings())

        return {
            'recent_legislation': recent_legislation,
            'recently_passed': recently_passed,
            'next_council_meeting': self.event_model.next_city_council_meeting(),
            'upcoming_committee_meetings': upcoming_meetings,
        }


class AboutView(TemplateView):
    template_name = 'councilmatic_core/about.html'

class CouncilMembersView(ListView):
    template_name = 'councilmatic_core/council_members.html'
    context_object_name = 'posts'
    
    def get_queryset(self):
        return Organization.objects.get(ocd_id=settings.OCD_CITY_COUNCIL_ID).posts.all()
        # return Post.objects.filter(organization__ocd_id=settings.OCD_CITY_COUNCIL_ID)

class BillDetailView(DetailView):
    model = Bill
    template_name = 'councilmatic_core/legislation.html'
    context_object_name = 'legislation'
    
    def get_context_data(self, **kwargs):
        context = super(BillDetailView, self).get_context_data(**kwargs)
        
        context['actions'] = self.get_object().actions.all().order_by('-order')
        
        return context

class CommitteesView(ListView):
    template_name = 'councilmatic_core/committees.html'
    context_object_name = 'committees'

    def get_queryset(self):
        return Organization.committees().filter(name__startswith='Committee')

class CommitteeDetailView(DetailView):
    model = Organization
    template_name = 'councilmatic_core/committee.html'
    context_object_name = 'committee'
    
    def get_context_data(self, **kwargs):
        context = super(CommitteeDetailView, self).get_context_data(**kwargs)
        
        committee = context['committee']
        context['chairs'] = committee.memberships.filter(role='CHAIRPERSON')
        context['memberships'] = committee.memberships.filter(role='Committee Member')
        
        if getattr(settings, 'COMMITTEE_DESCRIPTIONS', None):
            description = settings.COMMITTEE_DESCRIPTIONS.get(self.get_slug())
            context['committee_description'] = description

        return context

class PersonDetailView(DetailView):
    model = Person
    template_name = 'councilmatic_core/person.html'
    context_object_name = 'person'
    
    def get_context_data(self, **kwargs):
        context = super(PersonDetailView, self).get_context_data(**kwargs)
        
        person = context['person']
        context['sponsored_legislation'] = [s.bill for s in person.primary_sponsorships.order_by('-_bill__last_action_date')]
        context['chairs'] = person.memberships.filter(role="CHAIRPERSON")
        context['memberships'] = person.memberships.filter(role="Committee Member")
        
        return context


class EventsView(ListView):
    template_name = 'councilmatic_core/events.html'

    def get_queryset(self):
        # Realize this is stupid. The reason this exists is so that
        # we can have this be a ListView in the inherited subclasses
        # if needed
        return []

    def get_context_data(self, **kwargs):
        context = super(EventsView, self).get_context_data(**kwargs)
        
        aggregates = Event.objects.aggregate(Min('start_time'), Max('start_time'))
        min_year, max_year = aggregates['start_time__min'].year, aggregates['start_time__max'].year
        context['year_range'] = list(reversed(range(min_year, max_year + 1)))
        
        context['month_options'] = []
        for index in range(1, 13):
            month_name = datetime(date.today().year, index, 1).strftime('%B')
            context['month_options'].append([month_name, index])
        
        context['show_upcoming'] = True
        context['this_month'] = date.today().month
        context['this_year'] = date.today().year
        events_key = 'upcoming_events'

        upcoming_dates = Event.objects.filter(start_time__gt=date.today())
        
        current_year = self.request.GET.get('year')
        current_month = self.request.GET.get('month')
        if current_year and current_month:
            events_key = 'month_events'
            upcoming_dates = Event.objects\
                                  .filter(start_time__year=int(current_year))\
                                  .filter(start_time__month=int(current_month))
            
            context['show_upcoming'] = False
            context['this_month'] = int(current_month)
            context['this_year'] = int(current_year)
        
        upcoming_dates = upcoming_dates.order_by('start_time')
        
        day_grouper = lambda x: (x.start_time.year, x.start_time.month, x.start_time.day)
        context[events_key] = []
        
        for event_date, events in itertools.groupby(upcoming_dates, key=day_grouper):
            events = sorted(events, key=attrgetter('start_time'))
            context[events_key].append([date(*event_date), events])
        
        return context

class EventDetailView(DetailView):
    template_name = 'councilmatic_core/event.html'
    model = Event
    context_object_name = 'event'

    def get_context_data(self, **kwargs):
        context = super(EventDetailView, self).get_context_data(**kwargs)
        
        participants = [p.entity_name for p in context['event'].participants.all()]
        context['participants'] = Organization.objects.filter(name__in=participants)
        
        return context

def not_found(request):
    return render(request, 'councilmatic_core/404.html')
