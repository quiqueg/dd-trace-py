#!/usr/bin/env python3

""" This Flask application is imported on tests.appsec.appsec_utils.gunicorn_server
"""


from flask import Flask
from flask import request
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from ddtrace.appsec import _asm_request_context

from ddtrace.appsec._iast._taint_tracking import is_pyobject_tainted


import ddtrace.auto  # noqa: F401  # isort: skip


engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
app = Flask(__name__)

Base = declarative_base()


class User(Base):
    __tablename__ = "user_account"
    id = Column(Integer, primary_key=True)
    name = Column(String(30), nullable=True)


class ResultResponse:
    param = ""
    result1 = ""
    result2 = ""

    def __init__(self, param):
        self.param = param

    def json(self):
        return {
            "param": self.param,
            "result1": self.result1,
            "result2": self.result2,
            "params_are_tainted": is_pyobject_tainted(self.result1),
        }


@app.route("/")
def pkg_requests_view():
    param = request.args.get("param", "param")
    response = ResultResponse(param)
    session = sessionmaker(bind=engine)()

    with engine.connect() as connection:
        result = connection.execute("select * from user_account where name = '" + param + "'")

    response.result1 = param
    response.result2 = ""

    return response.json()


if __name__ == "__main__":
    User.metadata.create_all(engine, checkfirst=False)
    app.run(debug=False, port=8000)
