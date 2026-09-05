from pydantic import BaseModel, HttpUrl


class CheckoutSessionRead(BaseModel):
    url: HttpUrl
