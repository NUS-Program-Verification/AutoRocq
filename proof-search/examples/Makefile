COQPROJECT := _CoqProject
COQMF      := Makefile.coq
VFILES     := $(shell find . -type f -name '*.v' | sort)


.PHONY: all coq clean distclean print-vfiles rebuild

all: coq
coq: $(COQMF)
	$(MAKE) -f $(COQMF) -j all

$(COQMF): $(COQPROJECT) $(VFILES)
	@echo "Generating $(COQMF) with $$(echo $(VFILES) | wc -w) files"
	@test $$(echo $(VFILES) | wc -w) -gt 0 || { echo "No .v files found for coq_makefile"; exit 1; }
	coq_makefile -f $(COQPROJECT) $(VFILES) -o $(COQMF)

print-vfiles:
	@printf "%s\n" $(VFILES)

rebuild: distclean all

clean:
	@if [ -f $(COQMF) ]; then $(MAKE) -f $(COQMF) clean; fi

distclean: clean
	@rm -f $(COQMF) $(COQMF).conf
	@find . -type f \( -name '*.vo' -o -name '*.vos' -o -name '*.vok' -o -name '*.glob' -o -name 'coqpyt_aux_*' \) -delete
