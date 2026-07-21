"""
reload() instead of instance.refresh_from_db() for models with a
django-fsm protected=True field (Sample, TestRequest, TrainingSession,
Enrollment): FSMFieldDescriptor.__set__ raises AttributeError on any direct
assignment once the field name is already in instance.__dict__, and
Model.refresh_from_db() does exactly that direct setattr for every field --
these models don't mix in django_fsm's FSMModelMixin (which overrides
refresh_from_db to skip protected fields), so calling it on them raises.
Fetching a brand-new instance sidesteps the descriptor's protection check
entirely, since protection only fires on a second assignment to the same
instance.
"""


def reload(instance):
    return type(instance).objects.get(pk=instance.pk)
