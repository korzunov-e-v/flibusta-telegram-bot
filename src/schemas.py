from pydantic import BaseModel, EmailStr


class EmailData(BaseModel):
    email: EmailStr
