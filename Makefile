SHELL:=bash
username?=$(shell whoami)

VENV_NAME?=_build/conda

PYTHON=${VENV_NAME}/bin/python
PIP=${VENV_NAME}/bin/pip

conda_url?="https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh"
operation?=update	

.PHONY: condaVenv
condaVenv:
	wget  ${conda_url} -O ~/miniconda.sh
	/bin/bash ~/miniconda.sh -b -p ${VENV_NAME}
	rm ~/miniconda.sh

.PHONY: clean
clean:
	rm -rf ${VENV_NAME}

.PHONY: clean-install
clean-install: clean condaVenv install

.PHONY: install
install:
	${PIP} install -r requirements.txt 

.PHONY: cloudformation-common
cloudformation-common:
	${PYTHON} cloudformation/cloudformation.py common ${operation}  ${config}

.PHONY: cloudformation-batch
cloudformation-batch: 
	${PYTHON} cloudformation/cloudformation.py batch ${operation}  ${config}  

.PHONY: cloudformation-cognito
cloudformation-cognito: 
	${PYTHON} cloudformation/cloudformation.py cognito ${operation}  ${config} 

