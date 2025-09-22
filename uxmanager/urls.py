"""
URL configuration for ux_manager project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("calificaciones/<slug:slug>/", views.company_ratings, name="calificaciones"),
    path("", views.home, name="home"),
]
