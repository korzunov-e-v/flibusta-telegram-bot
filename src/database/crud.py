from src.database.models import User
from src.database.session import SessionLocal


async def get_email(user_id: int) -> str | None:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)

        return user.email if user else None


async def set_email(user_id: int, email: str) -> None:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)

        if user is None:
            user = User(
                user_id=user_id,
                email=email,
            )
            session.add(user)
        else:
            user.email = email

        await session.commit()
