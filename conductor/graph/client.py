from neo4j import GraphDatabase
from conductor.config import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE


class Neo4jClient:
    def __init__(self):
        self._driver = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
        )
        self._database = NEO4J_DATABASE

    def close(self):
        self._driver.close()

    def verify_connectivity(self):
        self._driver.verify_connectivity()
        print(f"Connected to Neo4j at {NEO4J_URI}")

    def run_query(self, query: str, parameters: dict = None):
        with self._driver.session(database=self._database) as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]

    def run_write(self, query: str, parameters: dict = None):
        with self._driver.session(database=self._database) as session:
            result = session.execute_write(
                lambda tx: tx.run(query, parameters or {}).consume()
            )
            return result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
