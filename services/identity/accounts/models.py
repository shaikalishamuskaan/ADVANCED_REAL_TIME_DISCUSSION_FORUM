
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


username_validator = RegexValidator(
    regex=r"^[A-Za-z0-9_]{3,30}$",
    message="Username must contain 3 to 30 letters, digits, or underscores.",
)


class UserManager(BaseUserManager):
    """Create users with normalized usernames and email addresses."""

    def create_user(self, email, username, password=None, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        if not username:
            raise ValueError("A username is required.")
        if not password:
            raise ValueError("A password is required.")

        email = self.normalize_email(email).strip().lower()
        username = username.strip()

        user = self.model(
            email=email,
            username=username,
            username_normalized=username.lower(),
            **extra_fields,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault("role", "admin")
        extra_fields.setdefault("status", "active")

        return self.create_user(email, username, password, **extra_fields)


class User(AbstractBaseUser):
    """Forum user account, following the Identity LLD schema."""

    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        MODERATOR = "moderator", "Moderator"
        ADMIN = "admin", "Admin"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    username = models.CharField(
        max_length=30,
        validators=[username_validator],
    )
    username_normalized = models.CharField(
        max_length=30,
        unique=True,
        editable=False,
    )
    email = models.EmailField(unique=True, max_length=254)

    # Keep Django's authentication field name while using the LLD column name.
    password = models.CharField(max_length=128, db_column="password_hash")

    display_name = models.CharField(max_length=100)
    bio = models.TextField(blank=True, default="")
    avatar_url = models.CharField(max_length=2048, blank=True, null=True)

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    status = models.CharField(
        max_length=8,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # The LLD USER table does not include Django's last_login column.
    last_login = None

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "display_name"]

    class Meta:
        db_table = "users"
        constraints = [
            models.CheckConstraint(
                condition=Q(role__in=["member", "moderator", "admin"]),
                name="user_role_valid",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["active", "disabled"]),
                name="user_status_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        self.username_normalized = self.username.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    @property
    def is_staff(self):
        return self.role == self.Role.ADMIN

    @property
    def is_superuser(self):
        return self.role == self.Role.ADMIN

    def has_perm(self, perm, obj=None):
        return self.is_active and self.is_staff

    def has_module_perms(self, app_label):
        return self.is_active and self.is_staff

    def __str__(self):
        return self.username
