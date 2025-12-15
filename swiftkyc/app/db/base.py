from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Import models ONLY for metadata creation
# DO NOT import them at top-level inside tasks or models
def init_models():
    import app.models.customer
    import app.models.kyc_session
    import app.models.kyc_document
