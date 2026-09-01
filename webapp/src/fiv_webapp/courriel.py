"""L'envoi de courriels — un seul aujourd'hui : le code de vérification.

`smtplib` de la bibliothèque standard, dans un thread (`asyncio.to_thread`) :
un envoi SMTP est bloquant et rare — une dépendance asynchrone dédiée serait
un coût permanent pour un besoin épisodique.

Sans configuration SMTP, le code part dans le JOURNAL du service et nulle
part ailleurs : le poste de dev n'envoie pas de vrais mails, et la
production sans `SMTP_HOST` le dit à chaque tentative plutôt que d'échouer
en silence.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)

# Le sujet et le corps, par langue — les quatre du site.
_SUJETS = {
    "fr": "Votre code FIVO : {code}",
    "en": "Your FIVO code: {code}",
    "es": "Tu código FIVO: {code}",
    "ar": "رمز فيفو الخاص بك: {code}",
}
_CORPS = {
    "fr": (
        "Bonjour {pseudo},\n\n"
        "Votre code de vérification FIVO : {code}\n\n"
        "Il expire dans 15 minutes. Si vous n'avez rien demandé, ignorez ce message.\n"
    ),
    "en": (
        "Hello {pseudo},\n\n"
        "Your FIVO verification code: {code}\n\n"
        "It expires in 15 minutes. If you didn't ask for it, ignore this message.\n"
    ),
    "es": (
        "Hola {pseudo}:\n\n"
        "Tu código de verificación FIVO: {code}\n\n"
        "Caduca en 15 minutos. Si no lo has pedido, ignora este mensaje.\n"
    ),
    "ar": (
        "مرحبًا {pseudo}،\n\n"
        "رمز التحقق الخاص بك في فيفو: {code}\n\n"
        "تنتهي صلاحيته خلال 15 دقيقة. إن لم تطلبه، تجاهل هذه الرسالة.\n"
    ),
}


class Courriel:
    """Le service d'envoi, configuré une fois au démarrage."""

    def __init__(
        self,
        hote: str = "",
        *,
        port: int = 587,
        utilisateur: str = "",
        mot_de_passe: str = "",
        expediteur: str = "",
    ) -> None:
        self._hote = hote
        self._port = port
        self._utilisateur = utilisateur
        self._mot_de_passe = mot_de_passe
        self._expediteur = expediteur or utilisateur

    @property
    def configure(self) -> bool:
        return bool(self._hote)

    async def envoyer_code(self, email: str, pseudo: str, code: str, langue: str = "fr") -> bool:
        """Envoie le code — ou l'écrit au journal quand rien n'est configuré.

        Ne lève jamais vers la route : un SMTP en panne ne doit pas rendre
        l'inscription impossible à diagnostiquer — l'erreur va au journal, et
        « renvoyer le code » reste le geste de l'utilisateur. Le booléen
        rendu dit si l'envoi a RÉELLEMENT eu lieu : la route l'ignore, la
        commande de test s'en sert pour ne pas annoncer « envoyé » à tort.
        """
        langue = langue if langue in _SUJETS else "fr"
        if not self.configure:
            log.warning(
                "SMTP non configuré — code de vérification pour %s : %s "
                "(renseigner SMTP_HOST pour envoyer de vrais courriels)",
                email,
                code,
            )
            return False
        message = EmailMessage()
        message["From"] = self._expediteur
        message["To"] = email
        message["Subject"] = _SUJETS[langue].format(code=code)
        message.set_content(_CORPS[langue].format(pseudo=pseudo, code=code))
        try:
            await asyncio.to_thread(self._expedier, message)
        except Exception:  # noqa: BLE001 — le journal dit tout, la route reste calme
            log.exception("envoi du code à %s impossible", email)
            return False
        return True

    def _expedier(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._hote, self._port, timeout=15) as smtp:
            smtp.starttls()
            if self._utilisateur:
                smtp.login(self._utilisateur, self._mot_de_passe)
            smtp.send_message(message)
