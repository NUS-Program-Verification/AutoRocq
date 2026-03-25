FROM ubuntu:22.04

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y build-essential
RUN apt-get install -y software-properties-common

RUN apt install -y python3.11-dev python3.11-venv
RUN apt install -y --fix-missing \
    git graphviz libcairo2-dev libexpat1-dev libgtk-3-dev libgtksourceview-3.0-dev \
    zlib1g-dev adwaita-icon-theme-full curl libgmp-dev pkg-config bubblewrap

RUN apt install python3-pip -y
RUN python3 -m pip install openai

RUN apt update && apt install -y opam m4
RUN opam init -y --bare --disable-sandboxing
RUN opam switch create 4.14.0 ocaml-base-compiler.4.14.0 -y --jobs=1
RUN eval $(opam env) && opam install dune -y

RUN opam repo add coq-released https://coq.inria.fr/opam/released

RUN apt-get install python2.7 vim -y

RUN git clone https://github.com/NUS-Program-Verification/AutoRocq.git /autorocq

WORKDIR /autorocq/
RUN opam update && opam switch import deps.opam -y
ENV PATH="/root/.opam/4.14.0/bin:$PATH"
RUN pip install -r requirement.txt
