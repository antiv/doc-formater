"""Testovi identiteta i dozvola nad setovima pravila.

Model: formatiranje je otvoreno, vlasništvo traži prijavu, admin sme sve.
Zabrana izmene tuđeg seta mora ostati neblokirajuća — kopiranje je izlaz.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from docformat import identity
from docformat.identity import User
from docformat.rules import RuleSet, RuleSetMeta


def _rule_set(owner: str | None = None) -> RuleSet:
    return RuleSet(meta=RuleSetMeta(id="x", display_name="X", owner=owner))


ANA = User(email="ana@primer.com", name="Ana", is_admin=False)
MARKO = User(email="marko@primer.com", name="Marko", is_admin=False)
ADMIN = User(email="sef@primer.com", name="Šef", is_admin=True)


class CanEditTest(unittest.TestCase):
    def test_anonymous_may_not_edit_anything(self) -> None:
        self.assertFalse(identity.can_edit(_rule_set("ana@primer.com"), None))
        self.assertFalse(identity.can_edit(_rule_set(None), None))

    def test_owner_may_edit_own_set(self) -> None:
        self.assertTrue(identity.can_edit(_rule_set("ana@primer.com"), ANA))

    def test_owner_comparison_ignores_case(self) -> None:
        """Google ume da vrati email u drugom pisanju nego što je zapisan."""
        self.assertTrue(identity.can_edit(_rule_set("Ana@Primer.com"), ANA))

    def test_user_may_not_edit_someone_elses_set(self) -> None:
        self.assertFalse(identity.can_edit(_rule_set("ana@primer.com"), MARKO))

    def test_admin_may_edit_everything(self) -> None:
        self.assertTrue(identity.can_edit(_rule_set("ana@primer.com"), ADMIN))
        self.assertTrue(identity.can_edit(_rule_set(None), ADMIN))

    def test_unowned_set_is_admin_only(self) -> None:
        """Ugrađeni preset ne sme da postane vlasništvo prvog ko naiđe."""
        self.assertFalse(identity.can_edit(_rule_set(None), ANA))
        self.assertTrue(identity.can_edit(_rule_set(None), ADMIN))


class CanCreateTest(unittest.TestCase):
    def test_saving_requires_an_identity(self) -> None:
        self.assertFalse(identity.can_create(None))
        self.assertTrue(identity.can_create(ANA))


class AdminEmailsTest(unittest.TestCase):
    @mock.patch.dict(os.environ, {"ADMIN_EMAILS": "A@primer.com, b@primer.com"}, clear=True)
    def test_parsed_and_normalized(self) -> None:
        self.assertEqual({"a@primer.com", "b@primer.com"}, identity.admin_emails())

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_empty_by_default(self) -> None:
        self.assertEqual(set(), identity.admin_emails())


class CurrentUserTest(unittest.TestCase):
    class FakeSecrets(dict):
        pass

    class FakeStreamlit:
        def __init__(self, secrets, user=None):
            self.secrets = secrets
            self.user = user

    class FakeUser:
        def __init__(self, logged_in, email="", name=""):
            self.is_logged_in = logged_in
            self.email = email
            self.name = name

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_without_oidc_the_local_user_is_admin(self) -> None:
        """Bez podešene prijave razvojna mašina ne sme da ostane zaključana."""
        st = self.FakeStreamlit(secrets={})
        user = identity.current_user(st)
        self.assertIsNotNone(user)
        self.assertTrue(user.is_admin)
        self.assertTrue(user.is_local)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_with_oidc_but_not_logged_in_is_anonymous(self) -> None:
        st = self.FakeStreamlit(secrets={"auth": {}}, user=self.FakeUser(False))
        self.assertIsNone(identity.current_user(st))

    @mock.patch.dict(os.environ, {"ADMIN_EMAILS": "sef@primer.com"}, clear=True)
    def test_logged_in_user_is_resolved(self) -> None:
        st = self.FakeStreamlit(
            secrets={"auth": {}}, user=self.FakeUser(True, "ana@primer.com", "Ana")
        )
        user = identity.current_user(st)
        self.assertEqual("ana@primer.com", user.email)
        self.assertEqual("Ana", user.name)
        self.assertFalse(user.is_admin)

    @mock.patch.dict(os.environ, {"ADMIN_EMAILS": "SEF@primer.com"}, clear=True)
    def test_admin_flag_from_env_is_case_insensitive(self) -> None:
        st = self.FakeStreamlit(
            secrets={"auth": {}}, user=self.FakeUser(True, "sef@primer.com", "Šef")
        )
        self.assertTrue(identity.current_user(st).is_admin)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_logged_in_without_email_is_treated_as_anonymous(self) -> None:
        """Bez email-a nema stabilnog identiteta, pa nema ni vlasništva."""
        st = self.FakeStreamlit(secrets={"auth": {}}, user=self.FakeUser(True, "", "Bez"))
        self.assertIsNone(identity.current_user(st))


class GateTest(unittest.TestCase):
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_open_without_password(self) -> None:
        self.assertTrue(identity.gate_is_open())

    @mock.patch.dict(os.environ, {"APP_PASSWORD": "   "}, clear=True)
    def test_blank_password_counts_as_unset(self) -> None:
        self.assertTrue(identity.gate_is_open())

    @mock.patch.dict(os.environ, {"APP_PASSWORD": "tajna"}, clear=True)
    def test_password_closes_the_gate(self) -> None:
        self.assertFalse(identity.gate_is_open())

    def test_password_comparison(self) -> None:
        self.assertTrue(identity.check_password(" tajna \n", "tajna"))
        self.assertFalse(identity.check_password("druga", "tajna"))
        self.assertFalse(identity.check_password("", None))


class DescribePermissionTest(unittest.TestCase):
    def test_anonymous_is_told_to_log_in(self) -> None:
        self.assertIn("Prijavi se", identity.describe_permission(_rule_set("a@b.com"), None))

    def test_foreign_set_suggests_copying(self) -> None:
        message = identity.describe_permission(_rule_set("ana@primer.com"), MARKO)
        self.assertIn("kopiju", message)
        self.assertIn("ana@primer.com", message)

    def test_own_set(self) -> None:
        self.assertIn("tvoj", identity.describe_permission(_rule_set("ana@primer.com"), ANA))


if __name__ == "__main__":
    unittest.main()
