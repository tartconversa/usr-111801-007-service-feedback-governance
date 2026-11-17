from .audit import history
from .catalog import Catalog
from .citations import Citations
from .db import connect
from .delivery import Delivery
from .grants import Grants
from .policy import Policies
from .products import Products
from .redactions import Redactions
from .reviews import Reviews


class Exchange:
    def __init__(self, database):
        self.connection = connect(database)
        self.catalog = Catalog(self.connection)
        self.grants = Grants(self.connection)
        self.policies = Policies(self.connection)
        self.products = Products(self.connection)
        self.delivery = Delivery(self.connection)
        self.redactions = Redactions(self.connection)
        self.reviews = Reviews(self.connection)
        self.citations = Citations(self.connection)

    def history(self, subject):
        return history(self.connection, subject)

    def close(self):
        self.connection.close()
