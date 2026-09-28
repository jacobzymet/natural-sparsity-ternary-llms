# Reproduction environment for the matched timing and power studies.
#
#   docker build -t ternary-eda synthesis/docker
#   docker run --rm -v "$PWD:/work" -w /work ternary-eda bash synthesis/run_timing_study.sh
FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive
ARG OPENSTA_COMMIT=d31c9429cd096d19a1af3e3f1c9fe4a22c310d46
ARG ORFS_COMMIT=db8b985f89d456db29d39588443a025e7305a0a6

RUN apt-get update && apt-get install -y --no-install-recommends \
        yosys iverilog python3 curl ca-certificates git build-essential cmake swig \
        bison flex libfl-dev tcl-dev libeigen3-dev zlib1g-dev libgtest-dev \
        autoconf automake libtool \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch cudd-3.0.0 https://github.com/cuddorg/cudd.git /tmp/cudd \
    && cd /tmp/cudd && autoreconf -fi && ./configure --prefix=/opt/cudd \
    && make -j"$(nproc)" && make install && rm -rf /tmp/cudd

RUN git clone https://github.com/The-OpenROAD-Project/OpenSTA.git /opt/OpenSTA \
    && git -C /opt/OpenSTA checkout ${OPENSTA_COMMIT} \
    && cmake -S /opt/OpenSTA -B /opt/OpenSTA/build -DCUDD_DIR=/opt/cudd -DCMAKE_BUILD_TYPE=Release \
    && cmake --build /opt/OpenSTA/build -j"$(nproc)" \
    && ln -s /opt/OpenSTA/build/sta /usr/local/bin/sta

RUN mkdir -p /opt/nangate45 && curl -L --fail \
        https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD-flow-scripts/${ORFS_COMMIT}/flow/platforms/nangate45/lib/NangateOpenCellLibrary_typical.lib \
        -o /opt/nangate45/NangateOpenCellLibrary_typical.lib

RUN apt-get update && apt-get install -y --no-install-recommends python3-numpy \
    && rm -rf /var/lib/apt/lists/*

ENV LIBERTY=/opt/nangate45/NangateOpenCellLibrary_typical.lib
