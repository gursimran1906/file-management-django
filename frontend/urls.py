from django.urls import path

from .views import index_view, root_view

urlpatterns = [
    path('', root_view, name='root'),
    path('index/', index_view, name='index'),
    # Other URL patterns
]
