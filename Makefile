# Everything except `images` runs without a GPU, which is what CI relies on.
PY := uv run python

.PHONY: all update images site serve clean hours-diff hours-accept verify

all: update site           ## scrape the week and rebuild the site

update:                    ## scrape the rolling 7-day menu window
	$(PY) scripts/update.py

images:                    ## draw the dishes still missing pictures (needs local ComfyUI)
	$(PY) scripts/gen_images.py

site:                      ## render site/ from data/
	$(PY) scripts/build_site.py

verify:                    ## re-fetch today's dinner live and diff it against data/
	$(PY) scripts/verify.py --day $$(date +%Y-%m-%d) --meal Dinner \
	  --halls arrillaga,lakeside,wilbur,stern,florencemoore,ricker,gerhardcasper,branner

catalog:                   ## re-derive data/dishes.json after tuning classification
	$(PY) scripts/rebuild_catalog.py
	$(PY) scripts/build_site.py

serve: site                ## preview at http://127.0.0.1:8777
	@cd site && python3 -m http.server 8777 --bind 127.0.0.1

hours-diff:                ## show how the R&DE hours page changed
	$(PY) scripts/update.py --show-hours-diff

hours-accept:              ## record the current hours page as the new baseline
	$(PY) scripts/update.py --accept-hours

clean:
	rm -rf site
