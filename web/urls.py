"""
URL eventuration for web project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# from django.contrib import admin
from django.urls import path
from . import views

event_url_pattern: str = '/'.join([
    'event',
    '<str:event_id>',
])
login_url_pattern: str = '/'.join([
    'login',
    '<str:event_id>',
])
screen_url_pattern: str = '/'.join([
    'screen',
    '<str:event_id>',
    '<str:screen_id>',
])
rotator_url_pattern: str = '/'.join([
    'rotator',
    '<str:event_id>',
    '<str:rotator_id>',
])
rotator_screen_url_pattern: str = '/'.join([
    'rotator',
    '<str:event_id>',
    '<str:rotator_id>',
    '<int:screen_index>',
])
result_url_pattern: str = '/'.join([
    'result',
    '<str:event_id>',
    '<str:screen_id>',
    '<str:tournament_id>',
    '<int:board_id>',
    '<int:result>',
])
last_update_url_pattern: str = '/'.join([
    'screen-last-update',
    '<str:event_id>',
    '<str:screen_id>',
])
urlpatterns = [
    path('', views.index, name='index'),
    path(event_url_pattern, views.show_event, name='show-event'),
    path(screen_url_pattern, views.show_screen, name='show-screen'),
    path(rotator_url_pattern, views.show_rotator, name='show-rotator'),
    path(rotator_screen_url_pattern, views.show_rotator, name='show-rotator-screen'),
    path(result_url_pattern, views.update_result, name='update-result'),
    path(last_update_url_pattern, views.get_screen_last_update, name='get-screen-last-update'),
]
