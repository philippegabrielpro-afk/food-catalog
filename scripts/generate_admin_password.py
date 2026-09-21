"""Generate a password hash for FOOD_CATALOG_ADMIN_PASSWORD_HASH."""

from getpass import getpass

from app.auth import hash_password


def main() -> None:
    password = getpass("Nouveau mot de passe administrateur : ")
    confirmation = getpass("Confirmez le mot de passe : ")
    if password != confirmation:
        raise SystemExit("Les mots de passe ne correspondent pas.")
    if len(password) < 14:
        raise SystemExit("Utilisez au moins 14 caractères.")
    print(f"FOOD_CATALOG_ADMIN_PASSWORD_HASH='{hash_password(password)}'")


if __name__ == "__main__":
    main()
