PREFIX := /usr/local
LIBDIR := $(PREFIX)/lib/prometheus-exporters
UNITDIR := $(PREFIX)/lib/systemd/system
SCRIPTS := nest-exporter.py openweather-exporter.py hue-exporter.py
SERVICES := systemd/hue-exporter.service systemd/nest-exporter.service systemd/openweather-exporter.service

all:
	@echo 'Run `make install` to install'

requirements.txt:
	poetry export -f requirements.txt > $@

install: requirements.txt
	python3 -m venv --symlinks --clear $(LIBDIR)
	$(LIBDIR)/bin/pip install -r requirements.txt
	install $(SCRIPTS) $(LIBDIR)
	mkdir -p $(UNITDIR)
	install $(SERVICES) $(UNITDIR)


.PHONY: all install

