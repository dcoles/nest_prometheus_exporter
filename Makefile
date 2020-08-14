PREFIX := /usr/local
LIBDIR := $(PREFIX)/lib/prometheus-exporters
UNITDIR := $(PREFIX)/lib/systemd/system
SRCS := lib.py nest-exporter.py openweather-exporter.py hue-exporter.py
SERVICES := systemd/hue-exporter.service systemd/nest-exporter.service systemd/openweather-exporter.service

all:
	@echo 'Run `make install` to install'

requirements.txt:
	poetry export -f requirements.txt > $@

install: requirements.txt
	python3 -m venv --symlinks --clear $(LIBDIR)
	$(LIBDIR)/bin/pip install -r requirements.txt
	install $(SRCS) $(LIBDIR)
	mkdir -p $(UNITDIR)
	install $(SERVICES) $(UNITDIR)

reload:
	systemctl daemon-reload
	systemctl restart nest-exporter hue-exporter openweather-exporter


.PHONY: all install reload

