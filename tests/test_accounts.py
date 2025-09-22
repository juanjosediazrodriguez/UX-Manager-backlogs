import re

import pytest
from django.urls import reverse
from django.test import Client


@pytest.mark.django_db
def test_signup_form_errors_shows_message_and_preserves_fields(client: Client):
    url = reverse("account_signup")
    # Missing required password fields should trigger our banner
    data = {"display_name": "Ana", "role": "CANDIDATE", "email": "ana@example.com"}
    resp = client.post(url, data, follow=True)
    content = resp.content.decode()
    assert "Favor ingresar información válida en los campos obligatorios" in content
    # preserves entered email
    assert "ana@example.com" in content


@pytest.mark.django_db
def test_password_policy_requires_uppercase_and_number(client: Client):
    url = reverse("account_signup")
    data = {
        "display_name": "Luis",
        "role": "CANDIDATE",
        "email": "luis@example.com",
        "password1": "password",  # invalid (no uppercase/number)
        "password2": "password",
    }
    resp = client.post(url, data)
    assert resp.status_code == 200
    content = resp.content.decode()
    # Robust match handling Unicode in Windows consoles
    assert "La contrase" in content  # prefix of "contraseña"
    assert re.search(r"may(Ãº|ú)?scula|mayuscula", content, re.IGNORECASE)
    assert re.search(r"n(Ãº|ú)?mero|numero", content, re.IGNORECASE)


def test_google_login_cancelled_message(client: Client):
    # Allauth exposes this route name for cancel template
    url = reverse("socialaccount_login_cancelled")
    resp = client.get(url)
    assert resp.status_code == 200
    assert "No se pudo completar el inicio de sesión con Google" in resp.content.decode()


@pytest.mark.django_db
def test_login_page_has_register_question(client: Client):
    resp = client.get(reverse("account_login"))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "¿No tienes cuenta?" in body or "No tienes cuenta" in body
    assert reverse("account_signup") in body
