"""
reload() fetches a fresh instance instead of mutating one in place with
instance.refresh_from_db().

It exists for a bug that is now fixed: on a model with a django-fsm-2
protected=True field (Sample, TestRequest, TrainingSession, Enrollment),
FSMFieldDescriptor.__set__ raises AttributeError on any direct assignment
once the field name is already in instance.__dict__, and
Model.refresh_from_db() does exactly that direct setattr for every field.
All four models now mix in django_fsm.FSMModelMixin, which overrides
refresh_from_db() to skip protected fields, so refresh_from_db() works --
see tests/test_fsm_refresh_from_db.py. reload() is kept as a convenience
for tests that don't need to mutate the same instance in place.
"""


def reload(instance):
    return type(instance).objects.get(pk=instance.pk)
