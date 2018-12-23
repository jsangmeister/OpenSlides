from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import models, transaction
from django.utils.timezone import now
from jsonfield import JSONField

from ..utils.autoupdate import Element
from ..utils.cache import element_cache, get_element_id
from ..utils.models import RESTModelMixin
from .access_permissions import (
    ChatMessageAccessPermissions,
    ConfigAccessPermissions,
    CountdownAccessPermissions,
    HistoryAccessPermissions,
    ProjectorAccessPermissions,
    ProjectorMessageAccessPermissions,
    TagAccessPermissions,
)


class ProjectorManager(models.Manager):
    """
    Customized model manager to support our get_full_queryset method.
    """

    def get_full_queryset(self):
        """
        Returns the normal queryset with all projectors. In the background
        projector defaults are prefetched from the database.
        """
        return self.get_queryset().prefetch_related("projectiondefaults")


class Projector(RESTModelMixin, models.Model):
    # TODO: Fix docstring
    """
    Model for all projectors.

    The config field contains a dictionary which uses UUIDs as keys. Every
    element must have at least the property "name". The property "stable"
    is to set whether this element should disappear on prune or clear
    requests.

    Example:

    {
        "881d875cf01741718ca926279ac9c99c": {
            "name": "topics/topic",
            "id": 1
        },
        "191c0878cdc04abfbd64f3177a21891a": {
            "name": "core/countdown",
            "stable": true,
            "status": "stop",
            "countdown_time": 20,
            "visable": true,
            "default": 42
        },
        "db670aa8d3ed4aabb348e752c75aeaaf": {
            "name": "core/clock",
            "stable": true
        }
    }

    If the config field is empty or invalid the projector shows a default
    slide.

    There are two additional fields to control the behavior of the projector
    view itself: scale and scroll.

    The projector can be controlled using the REST API with POST requests
    on e. g. the URL /rest/core/projector/1/activate_elements/.
    """

    access_permissions = ProjectorAccessPermissions()

    objects = ProjectorManager()

    config = JSONField()

    scale = models.IntegerField(default=0)

    scroll = models.IntegerField(default=0)

    width = models.PositiveIntegerField(default=1024)

    height = models.PositiveIntegerField(default=768)

    name = models.CharField(max_length=255, unique=True, blank=True)

    blank = models.BooleanField(blank=False, default=False)

    class Meta:
        """
        Contains general permissions that can not be placed in a specific app.
        """

        default_permissions = ()
        permissions = (
            ("can_see_projector", "Can see the projector"),
            ("can_manage_projector", "Can manage the projector"),
            ("can_see_frontpage", "Can see the front page"),
        )


class ProjectionDefault(RESTModelMixin, models.Model):
    """
    Model for the projection defaults like motions, agenda, list of
    speakers and thelike. The name is the technical name like 'topics' or
    'motions'. For apps the name should be the app name to get keep the
    ProjectionDefault for apps generic. But it is possible to give some
    special name like 'list_of_speakers'. The display_name is the shown
    name on the front end for the user.
    """

    name = models.CharField(max_length=256)

    display_name = models.CharField(max_length=256)

    projector = models.ForeignKey(
        Projector, on_delete=models.CASCADE, related_name="projectiondefaults"
    )

    def get_root_rest_element(self):
        return self.projector

    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.display_name


class Tag(RESTModelMixin, models.Model):
    """
    Model for tags. This tags can be used for other models like agenda items,
    motions or assignments.
    """

    access_permissions = TagAccessPermissions()

    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ("name",)
        default_permissions = ()
        permissions = (("can_manage_tags", "Can manage tags"),)

    def __str__(self):
        return self.name


class ConfigStore(RESTModelMixin, models.Model):
    """
    A model class to store all config variables in the database.
    """

    access_permissions = ConfigAccessPermissions()

    key = models.CharField(max_length=255, unique=True, db_index=True)
    """A string, the key of the config variable."""

    value = JSONField()
    """The value of the config variable. """

    class Meta:
        default_permissions = ()
        permissions = (
            ("can_manage_config", "Can manage configuration"),
            ("can_manage_logos_and_fonts", "Can manage logos and fonts"),
        )

    @classmethod
    def get_collection_string(cls):
        return "core/config"


class ChatMessage(RESTModelMixin, models.Model):
    """
    Model for chat messages.

    At the moment we only have one global chat room for managers.
    """

    access_permissions = ChatMessageAccessPermissions()
    can_see_permission = "core.can_use_chat"

    message = models.TextField()

    timestamp = models.DateTimeField(auto_now_add=True)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        default_permissions = ()
        permissions = (
            ("can_use_chat", "Can use the chat"),
            ("can_manage_chat", "Can manage the chat"),
        )

    def __str__(self):
        return "Message {}".format(self.timestamp)


class ProjectorMessage(RESTModelMixin, models.Model):
    """
    Model for ProjectorMessages.
    """

    access_permissions = ProjectorMessageAccessPermissions()

    message = models.TextField(blank=True)

    class Meta:
        default_permissions = ()


class Countdown(RESTModelMixin, models.Model):
    """
    Model for countdowns.
    """

    access_permissions = CountdownAccessPermissions()

    description = models.CharField(max_length=256, blank=True)

    running = models.BooleanField(default=False)

    default_time = models.PositiveIntegerField(default=60)

    countdown_time = models.FloatField(default=60)

    class Meta:
        default_permissions = ()

    def control(self, action, skip_autoupdate=False):
        if action not in ("start", "stop", "reset"):
            raise ValueError(
                "Action must be 'start', 'stop' or 'reset', not {}.".format(action)
            )

        if action == "start":
            self.running = True
            self.countdown_time = now().timestamp() + self.default_time
        elif action == "stop" and self.running:
            self.running = False
            self.countdown_time = self.countdown_time - now().timestamp()
        else:  # reset
            self.running = False
            self.countdown_time = self.default_time
        self.save(skip_autoupdate=skip_autoupdate)


class HistoryData(models.Model):
    """
    Django model to save the history of OpenSlides.

    This is not a RESTModel. It is not cachable and can only be reached by a
    special viewset.
    """

    full_data = JSONField()

    class Meta:
        default_permissions = ()


class HistoryManager(models.Manager):
    """
    Customized model manager for the history model.
    """

    def add_elements(self, elements):
        """
        Method to add elements to the history. This does not trigger autoupdate.
        """
        with transaction.atomic():
            instances = []
            for element in elements:
                if (
                    element["disable_history"]
                    or element["collection_string"]
                    == self.model.get_collection_string()
                ):
                    # Do not update history for history elements itself or if history is disabled.
                    continue
                # HistoryData is not a root rest element so there is no autoupdate and not history saving here.
                data = HistoryData.objects.create(full_data=element["full_data"])
                instance = self.model(
                    element_id=get_element_id(
                        element["collection_string"], element["id"]
                    ),
                    information=element["information"],
                    user_id=element["user_id"],
                    full_data=data,
                )
                instance.save(
                    skip_autoupdate=True
                )  # Skip autoupdate and of course history saving.
                instances.append(instance)
        return instances

    def build_history(self):
        """
        Method to add all cachables to the history.
        """
        # TODO: Add lock to prevent multiple history builds at once. See #4039.
        instances = None
        if self.all().count() == 0:
            elements = []
            all_full_data = async_to_sync(element_cache.get_all_full_data)()
            for collection_string, data in all_full_data.items():
                for full_data in data:
                    elements.append(
                        Element(
                            id=full_data["id"],
                            collection_string=collection_string,
                            full_data=full_data,
                            information="",
                            user_id=None,
                            disable_history=False,
                        )
                    )
            instances = self.add_elements(elements)
        return instances


class History(RESTModelMixin, models.Model):
    """
    Django model to save the history of OpenSlides.

    This model itself is not part of the history. This means that if you
    delete a user you may lose the information of the user field here.
    """

    access_permissions = HistoryAccessPermissions()

    objects = HistoryManager()

    element_id = models.CharField(max_length=255)

    now = models.DateTimeField(auto_now_add=True)

    information = models.CharField(max_length=255)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )

    full_data = models.OneToOneField(HistoryData, on_delete=models.CASCADE)

    class Meta:
        default_permissions = ()
