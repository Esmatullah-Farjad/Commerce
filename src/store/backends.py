from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

UserModel = get_user_model()


class EmailBackend(ModelBackend):
    """
    Custom authentication backend that allows users to authenticate using their email and password.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticates a user based on the provided email and password.

        Args:
            request (HttpRequest): The current request object.
            email (str): The email of the user to authenticate.
            password (str): The password of the user to authenticate.

        Returns:
            User: The authenticated user if successful, None otherwise.
        """
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD, kwargs.get(UserModel.EMAIL_FIELD))
        if username is None or password is None:
            return
        try:
            user = UserModel.objects.get(email=username)
        except UserModel.DoesNotExist:
            return None

        except UserModel.MultipleObjectsReturned:
            # TODO: Handle with proper message
            return None

        if user.check_password(password) and user.is_active:
            return user

    def get_user(self, user_id):
        """
        Retrieves a user instance based on the user ID.

        Args:
            user_id (int): The ID of the user to retrieve.

        Returns:
            User: The user instance if found, None otherwise.
        """
        UserModel = get_user_model()
        try:
            return UserModel.objects.get(pk=user_id)
        except UserModel.DoesNotExist:
            return None
