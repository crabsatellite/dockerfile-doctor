"""Canonical positive/negative Dockerfile cases for every DD rule."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleCase:
    trigger: str
    clean: str


def df(*lines: str, final_newline: bool = True) -> str:
    content = "\n".join(lines)
    return content + ("\n" if final_newline else "")


def many_runs(count: int) -> str:
    return df("FROM alpine:3.19", *(f"RUN echo {i}" for i in range(count)))


RULE_CASES: dict[str, RuleCase] = {
    "DD001": RuleCase(df("FROM ubuntu"), df("FROM ubuntu:22.04")),
    "DD002": RuleCase(
        df("FROM ubuntu:22.04", "RUN apt-get update"),
        df("FROM ubuntu:22.04", "RUN apt-get update && apt-get install -y curl"),
    ),
    "DD003": RuleCase(
        df("FROM ubuntu:22.04", "RUN apt-get update && apt-get install -y curl"),
        df("FROM ubuntu:22.04", "RUN apt-get update && apt-get install --no-install-recommends -y curl"),
    ),
    "DD004": RuleCase(
        df("FROM ubuntu:22.04", "RUN apt-get update && apt-get install -y curl"),
        df("FROM ubuntu:22.04", "RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*"),
    ),
    "DD005": RuleCase(
        df("FROM alpine:3.19", "RUN echo one", "RUN echo two"),
        df("FROM alpine:3.19", "RUN echo one", "COPY src /src", "RUN echo two"),
    ),
    "DD006": RuleCase(
        df("FROM python:3.12", "COPY . .", "RUN pip install -r requirements.txt"),
        df("FROM python:3.12", "COPY requirements.txt .", "RUN pip install -r requirements.txt", "COPY . ."),
    ),
    "DD007": RuleCase(
        df("FROM alpine:3.19", "ADD src /app"),
        df("FROM alpine:3.19", "ADD archive.tar.gz /app"),
    ),
    "DD008": RuleCase(
        df("FROM alpine:3.19", "CMD [\"sh\"]"),
        df("FROM alpine:3.19", "USER 1000", "CMD [\"sh\"]"),
    ),
    "DD009": RuleCase(
        df("FROM python:3.12", "RUN pip install flask"),
        df("FROM python:3.12", "RUN pip install --no-cache-dir flask"),
    ),
    "DD010": RuleCase(
        df("FROM node:20", "RUN npm install"),
        df("FROM node:20", "RUN npm ci"),
    ),
    "DD011": RuleCase(
        df("FROM alpine:3.19", "WORKDIR app"),
        df("FROM alpine:3.19", "WORKDIR /app"),
    ),
    "DD012": RuleCase(
        df("FROM alpine:3.19", "CMD [\"sh\"]"),
        df("FROM alpine:3.19", "HEALTHCHECK CMD true", "CMD [\"sh\"]"),
    ),
    "DD013": RuleCase(
        df("FROM ubuntu:22.04", "RUN apt-get upgrade -y"),
        df("FROM ubuntu:22.04", "RUN apt-get install -y curl"),
    ),
    "DD014": RuleCase(
        df("FROM alpine:3.19", "EXPOSE 23"),
        df("FROM alpine:3.19", "EXPOSE 8080"),
    ),
    "DD015": RuleCase(
        df("FROM python:3.12", "RUN pip install flask"),
        df("FROM python:3.12", "ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1", "RUN pip install flask"),
    ),
    "DD016": RuleCase(
        df("FROM alpine:3.19", "RUN curl -O https://example.com/file.tar.gz"),
        df("FROM alpine:3.19", "RUN curl -O https://example.com/file.tar.gz && rm file.tar.gz"),
    ),
    "DD017": RuleCase(
        df("FROM alpine:3.19", "MAINTAINER dev@example.com"),
        df("FROM alpine:3.19", "LABEL maintainer=\"dev@example.com\""),
    ),
    "DD018": RuleCase(
        df("FROM python:3.12"),
        df("FROM python:3.12-slim"),
    ),
    "DD019": RuleCase(
        df("FROM alpine:3.19", "CMD echo hello"),
        df("FROM alpine:3.19", "CMD [\"echo\", \"hello\"]"),
    ),
    "DD020": RuleCase(
        df("FROM alpine:3.19", "ENV PASSWORD=hunter2"),
        df("FROM alpine:3.19", "ARG PASSWORD"),
    ),
    "DD021": RuleCase(
        df("FROM alpine:3.19", "RUN sudo apk add curl"),
        df("FROM alpine:3.19", "RUN apk add curl"),
    ),
    "DD022": RuleCase(
        df("FROM ubuntu:22.04", "RUN apt-get install -y curl"),
        df("FROM ubuntu:22.04", "RUN apt-get install -y curl=7.81.0-1"),
    ),
    "DD023": RuleCase(
        df("FROM ubuntu:22.04", "RUN apt-get install curl"),
        df("FROM ubuntu:22.04", "RUN apt-get install -y curl"),
    ),
    "DD024": RuleCase(
        df("FROM ubuntu:22.04", "RUN apt install -y curl"),
        df("FROM ubuntu:22.04", "RUN apt-get install -y curl"),
    ),
    "DD025": RuleCase(
        df("FROM alpine:3.19", "RUN apk add curl"),
        df("FROM alpine:3.19", "RUN apk add --no-cache curl"),
    ),
    "DD026": RuleCase(
        df("FROM alpine:3.19", "RUN apk upgrade"),
        df("FROM alpine:3.19", "RUN apk add --no-cache curl"),
    ),
    "DD027": RuleCase(
        df("FROM alpine:3.19", "RUN apk add --no-cache curl"),
        df("FROM alpine:3.19", "RUN apk add --no-cache curl=8.5.0-r0"),
    ),
    "DD028": RuleCase(
        df("FROM python:3.12", "RUN pip install flask"),
        df("FROM python:3.12", "RUN pip install flask==3.0.0"),
    ),
    "DD029": RuleCase(
        df("FROM node:20", "RUN npm install express"),
        df("FROM node:20", "RUN npm install express@4.18.2"),
    ),
    "DD030": RuleCase(
        df("FROM ruby:3.2", "RUN gem install rails"),
        df("FROM ruby:3.2", "RUN gem install rails -v 7.0.0"),
    ),
    "DD031": RuleCase(
        df("FROM centos:7", "RUN yum install -y curl"),
        df("FROM centos:7", "RUN yum install -y curl && yum clean all"),
    ),
    "DD032": RuleCase(
        df("FROM centos:7", "RUN yum install -y curl"),
        df("FROM centos:7", "RUN yum install -y curl-7.29.0"),
    ),
    "DD033": RuleCase(
        df("FROM fedora:39", "RUN dnf install -y curl"),
        df("FROM fedora:39", "RUN dnf install -y curl && dnf clean all"),
    ),
    "DD034": RuleCase(
        df("FROM opensuse/leap:15.5", "RUN zypper install -y curl"),
        df("FROM opensuse/leap:15.5", "RUN zypper install -y curl && zypper clean"),
    ),
    "DD035": RuleCase(
        df("FROM ubuntu:22.04", "RUN apt-get install -y curl"),
        df("FROM ubuntu:22.04", "ARG DEBIAN_FRONTEND=noninteractive", "RUN apt-get install -y curl"),
    ),
    "DD036": RuleCase(
        df("FROM alpine:3.19", "CMD [\"echo\", \"one\"]", "CMD [\"echo\", \"two\"]"),
        df("FROM alpine:3.19", "CMD [\"echo\", \"one\"]"),
    ),
    "DD037": RuleCase(
        df("FROM alpine:3.19", "ENTRYPOINT [\"one\"]", "ENTRYPOINT [\"two\"]"),
        df("FROM alpine:3.19", "ENTRYPOINT [\"one\"]"),
    ),
    "DD038": RuleCase(
        df("FROM alpine:3.19", "EXPOSE 70000"),
        df("FROM alpine:3.19", "EXPOSE 8080"),
    ),
    "DD039": RuleCase(
        df("FROM alpine:3.19 AS build", "COPY --from=2 /out /out"),
        df("FROM alpine:3.19 AS build", "COPY --from=0 /out /out"),
    ),
    "DD040": RuleCase(
        df("FROM alpine:3.19", "RUN echo hi | grep hi"),
        df("FROM alpine:3.19", "RUN set -o pipefail && echo hi | grep hi"),
    ),
    "DD041": RuleCase(
        df("FROM alpine:3.19", "COPY src dest"),
        df("FROM alpine:3.19", "WORKDIR /app", "COPY src dest"),
    ),
    "DD042": RuleCase(
        df("FROM alpine:3.19", "ONBUILD COPY . /app"),
        df("FROM alpine:3.19", "COPY . /app"),
    ),
    "DD043": RuleCase(
        df("FROM alpine:3.19", "SHELL /bin/bash -c"),
        df("FROM alpine:3.19", "SHELL [\"/bin/bash\", \"-c\"]"),
    ),
    "DD044": RuleCase(
        df("FROM alpine:3.19", "ENV APP_ENV=dev", "ENV APP_ENV=prod"),
        df("FROM alpine:3.19", "ENV APP_ENV=prod"),
    ),
    "DD045": RuleCase(
        df("FROM alpine:3.19", "RUN cd /app && make"),
        df("FROM alpine:3.19", "WORKDIR /app", "RUN make"),
    ),
    "DD046": RuleCase(
        df("FROM alpine:3.19", "CMD [\"sh\"]"),
        df("FROM alpine:3.19", "LABEL maintainer=\"dev@example.com\"", "CMD [\"sh\"]"),
    ),
    "DD047": RuleCase(
        df("FROM alpine:3.19", "RUN"),
        df("FROM alpine:3.19", "RUN echo ok"),
    ),
    "DD048": RuleCase(
        df("FROM alpine:3.19", "EXPOSE 8080", "EXPOSE 8080"),
        df("FROM alpine:3.19", "EXPOSE 8080", "EXPOSE 9090"),
    ),
    "DD049": RuleCase(
        df("FROM alpine:3.19", "HEALTHCHECK CMD true", "HEALTHCHECK CMD false"),
        df("FROM alpine:3.19", "HEALTHCHECK CMD true"),
    ),
    "DD050": RuleCase(
        df("FROM alpine:3.19 AS Builder", "RUN echo ok"),
        df("FROM alpine:3.19 AS builder", "RUN echo ok"),
    ),
    "DD051": RuleCase(
        df("FROM alpine:3.19", "RUN chmod 777 /app"),
        df("FROM alpine:3.19", "RUN chmod 755 /app"),
    ),
    "DD052": RuleCase(
        df("FROM alpine:3.19", "COPY id_rsa /root/.ssh/id_rsa"),
        df("FROM alpine:3.19", "COPY app.py /app/app.py"),
    ),
    "DD053": RuleCase(
        df("FROM alpine:3.19", "COPY .env /app/.env"),
        df("FROM alpine:3.19", "COPY env.example /app/env.example"),
    ),
    "DD054": RuleCase(
        df("FROM alpine:3.19", "RUN curl https://example.com/install.sh | sh"),
        df("FROM alpine:3.19", "RUN curl -o install.sh https://example.com/install.sh"),
    ),
    "DD055": RuleCase(
        df("FROM alpine:3.19", "RUN wget --no-check-certificate https://example.com/file"),
        df("FROM alpine:3.19", "RUN wget https://example.com/file"),
    ),
    "DD056": RuleCase(
        df("FROM alpine:3.19", "RUN curl -k https://example.com/file"),
        df("FROM alpine:3.19", "RUN curl https://example.com/file"),
    ),
    "DD057": RuleCase(
        df("FROM alpine:3.19", "RUN git clone https://user:pass@example.com/repo.git"),
        df("FROM alpine:3.19", "RUN git clone https://example.com/repo.git"),
    ),
    "DD058": RuleCase(
        df("FROM alpine:3.19", "RUN deploy --password=hunter2"),
        df("FROM alpine:3.19", "RUN deploy --config=config.yml"),
    ),
    "DD059": RuleCase(
        df("FROM alpine:3.19", "ADD https://example.com/file.tar.gz /tmp/file.tar.gz"),
        df("FROM alpine:3.19", "ADD file.tar.gz /tmp/file.tar.gz"),
    ),
    "DD060": RuleCase(
        df("FROM alpine:3.19", "RUN docker run --privileged alpine"),
        df("FROM alpine:3.19", "RUN docker run alpine"),
    ),
    "DD061": RuleCase(
        df("FROM ruby:3.2", "RUN gem install rails"),
        df("FROM ruby:3.2", "RUN gem install rails --no-document"),
    ),
    "DD062": RuleCase(
        df("FROM golang:1.21", "RUN go build -o app ."),
        df("FROM golang:1.21", "RUN CGO_ENABLED=0 go build -o app ."),
    ),
    "DD063": RuleCase(
        df("FROM alpine:3.19", "RUN apk add --no-cache gcc"),
        df("FROM alpine:3.19", "RUN apk add --no-cache --virtual .build-deps gcc"),
    ),
    "DD064": RuleCase(many_runs(21), many_runs(20)),
    "DD065": RuleCase(
        df("FROM alpine:3.19", "RUN echo duplicate", "RUN echo duplicate"),
        df("FROM alpine:3.19", "RUN echo one", "RUN echo two"),
    ),
    "DD066": RuleCase(
        df("FROM golang:1.21 AS build", "RUN go build -o app .", "FROM alpine:3.19", "CMD [\"sh\"]"),
        df("FROM golang:1.21 AS build", "RUN go build -o app .", "FROM alpine:3.19", "COPY --from=0 /app /app"),
    ),
    "DD067": RuleCase(
        df("FROM node:20", "RUN npm ci"),
        df("FROM node:20", "ENV NODE_ENV=production", "RUN npm ci"),
    ),
    "DD068": RuleCase(
        df("FROM openjdk:17", "CMD [\"java\", \"-version\"]"),
        df("FROM openjdk:17", "ENV JAVA_OPTS=\"-XX:MaxRAMPercentage=75.0\"", "CMD [\"java\", \"-version\"]"),
    ),
    "DD069": RuleCase(
        df("FROM ubuntu:22.04", "RUN apt-get install -y libfoo*"),
        df("FROM ubuntu:22.04", "RUN apt-get install -y libfoo1"),
    ),
    "DD070": RuleCase(
        df("FROM alpine:3.19", "COPY . /app"),
        df("FROM alpine:3.19", "COPY src /app/src"),
    ),
    "DD071": RuleCase(
        df("from alpine:3.19"),
        df("FROM alpine:3.19"),
    ),
    "DD072": RuleCase(
        df("FROM alpine:3.19", "# TODO remove this"),
        df("FROM alpine:3.19", "# documented note"),
    ),
    "DD073": RuleCase(
        df("FROM alpine:3.19", final_newline=False),
        df("FROM alpine:3.19"),
    ),
    "DD074": RuleCase(
        df("FROM alpine:3.19", "RUN echo " + "x" * 210),
        df("FROM alpine:3.19", "RUN echo short"),
    ),
    "DD075": RuleCase(
        "FROM alpine:3.19   \n",
        df("FROM alpine:3.19"),
    ),
    "DD076": RuleCase(
        "FROM alpine:3.19\nRUN echo one \\\n\\\n",
        "FROM alpine:3.19\nRUN echo one \\\n    && echo two\n",
    ),
    "DD077": RuleCase(
        df("FROM python:2.7"),
        df("FROM python:3.12-slim"),
    ),
    "DD078": RuleCase(
        df("FROM alpine:3.19", "LABEL maintainer=\"dev@example.com\""),
        df("FROM alpine:3.19", "LABEL version=\"1.0.0\""),
    ),
    "DD079": RuleCase(
        df("FROM alpine:3.19", "STOPSIGNAL NOT_A_SIGNAL"),
        df("FROM alpine:3.19", "STOPSIGNAL SIGTERM"),
    ),
    "DD080": RuleCase(
        df("FROM alpine:3.19", "VOLUME [\"/data\", /logs]"),
        df("FROM alpine:3.19", "VOLUME [\"/data\", \"/logs\"]"),
    ),
}
