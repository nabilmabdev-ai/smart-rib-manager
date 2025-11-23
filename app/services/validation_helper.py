import re
from fastapi import HTTPException

def validate_name(name: str, field_name: str):
    """
    Validates a name string to ensure it does not contain digits or special symbols,
    allowing only letters, spaces, and hyphens.

    Args:
        name (str): The name string to validate.
        field_name (str): The name of the field being validated (e.g., "first name", "last name")
                          for better error messages.

    Raises:
        HTTPException: If the name contains invalid characters.
    """
    if not re.fullmatch(r"[\p{L}\s-]+", name, re.UNICODE):
        raise HTTPException(
            status_code=400,
            detail=f"Le champ '{field_name}' contient des caractères invalides. Seules les lettres, les espaces et les tirets sont autorisés."
        )

