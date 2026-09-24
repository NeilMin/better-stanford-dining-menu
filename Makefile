# Everything except `images` runs without a GPU, which is what CI relies on.
PY := uv run python

.PHONY: all test update prompts images images-todo logos logos-check specials translate site serve \
        clean hours-diff hours-accept verify catalog source-check

all: update site           ## scrape the week and rebuild the site

test:                      ## run the test suite (no network, no GPU, ~2s)
	uv run pytest

update:                    ## scrape the rolling 7-day menu window
	$(PY) scripts/update.py

prompts:                   ## compile structured food prompts via Cloudflare LLM
	$(PY) scripts/compile_prompts.py

images:                    ## draw the dishes still missing pictures (needs local ComfyUI)
	$(PY) scripts/gen_images.py

images-todo:               ## print the dishes still waiting for a picture
	$(PY) scripts/notify_images.py --dry-run

logos:                     ## cut the hall logos out of the R&DE map into data/logos/
	$(PY) scripts/fetch_logos.py

logos-check:               ## has R&DE redrawn the map the logo boxes point into?
	$(PY) scripts/fetch_logos.py --check

specials:                  ## follow the specials calendar link on the hours page
	$(PY) scripts/fetch_specials.py

translate:                 ## fill in the missing Chinese (needs the claude CLI)
	$(PY) scripts/translate.py

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

source-check:              ## is R&DE offering a hall config/halls.json has never heard of?
	$(PY) scripts/check_source.py

clean:
	rm -rf site
