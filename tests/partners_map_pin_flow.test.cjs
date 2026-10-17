const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const partnersHtml = fs.readFileSync(
  path.join(__dirname, "..", "partners.html"),
  "utf8",
);

function extractFunction(name) {
  const match = partnersHtml.match(
    new RegExp(`^function ${name}\\([^\\n]*\\n([\\s\\S]*?)^}`, "m"),
  );
  assert.ok(match, `partners.html must define ${name}()`);
  return `function ${name}(${match[0].match(/^function \w+\(([^)]*)\)/)[1]}) {\n${match[1]}}`;
}

class FakeElement {
  constructor() {
    this.innerHTML = "";
    this.textContent = "";
    this.style = {};
    this.attributes = {};
    this.children = [];
    this.listeners = new Map();
    this.classList = {
      values: new Set(),
      add(value) {
        this.values.add(value);
      },
      remove(value) {
        this.values.delete(value);
      },
      contains(value) {
        return this.values.has(value);
      },
    };
  }

  removeAttribute(name) {
    delete this.attributes[name];
    if (name === "src") this.src = "";
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  addEventListener(name, handler) {
    const handlers = this.listeners.get(name) || [];
    handlers.push(handler);
    this.listeners.set(name, handlers);
  }

  dispatch(name, event = {}) {
    for (const handler of this.listeners.get(name) || []) handler(event);
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = [...children];
  }
}

function makeMapHarness() {
  const ids = [
    "partners-grid",
    "filter-bar",
    "map-wrapper",
    "map-pins",
    "map-legend",
    "modal-letter",
    "modal-category",
    "modal-name",
    "modal-area",
    "modal-desc",
    "modal-point",
    "modal-point-courses",
    "modal-point-courses-text",
    "modal-photo",
    "modal-stylist",
    "modal-btn",
    "modal-coming-soon",
    "modal-overlay",
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, new FakeElement()]));
  const filterButtons = [new FakeElement(), new FakeElement()];
  const partnerPinLayer = {
    markers: [],
    clearLayers() {
      this.markers.length = 0;
    },
  };
  const map = { fittedBounds: null, fitBounds(bounds) { this.fittedBounds = bounds; } };
  const partners = [
    {
      id: "hair-partner-id",
      marker: "01",
      name: "栄ヘアサロン",
      cat: "hair",
      area: "名古屋市中区",
      desc: "ヘアサロンの詳細",
      point: 120,
      point_courses: "通常カット\nカラーコース",
      photo: "",
      url: "https://example.com/hair",
      real: true,
      x: 20,
      y: 30,
    },
    {
      id: "hotel-partner-id",
      marker: "02",
      name: "名駅ホテル",
      cat: "hotel",
      area: "名古屋市中村区",
      desc: "ホテルの詳細",
      point: 250,
      point_courses: "",
      photo: "",
      url: "https://example.com/hotel",
      real: true,
      x: 60,
      y: 70,
    },
    {
      id: "same-location-partner-id",
      marker: "03",
      name: "栄の別パートナー",
      cat: "hotel",
      area: "名古屋市中区",
      desc: "同じ座標にある提携先の詳細",
      point: 180,
      point_courses: "",
      photo: "",
      url: "https://example.com/same-location",
      real: true,
      x: 20,
      y: 30,
    },
    {
      id: "same-location-cafe-id",
      marker: "04",
      name: "栄のカフェ",
      cat: "hotel",
      area: "名古屋市中区",
      desc: "カフェの詳細",
      point: 90,
      point_courses: "",
      photo: "",
      url: "https://example.com/sakae-cafe",
      real: true,
      x: 20,
      y: 30,
    },
    {
      id: "same-location-restaurant-id",
      marker: "05",
      name: "栄のレストラン",
      cat: "hair",
      area: "名古屋市中区",
      desc: "レストランの詳細",
      point: 210,
      point_courses: "",
      photo: "",
      url: "https://example.com/sakae-restaurant",
      real: true,
      x: 20,
      y: 30,
    },
  ];
  const sandbox = {
    PARTNERS: partners,
    CATEGORIES: { hair: "美容", hotel: "ホテル" },
    activeFilter: "all",
    document: {
      body: { style: {} },
      documentElement: new FakeElement(),
      getElementById(id) {
        return elements[id];
      },
      createElement() {
        return new FakeElement();
      },
      querySelectorAll(selector) {
        assert.equal(selector, ".filter-btn");
        return elements["filter-bar"].children.length
          ? elements["filter-bar"].children
          : filterButtons;
      },
    },
    ensurePartnerMap() {
      return true;
    },
    partnerPinLayer,
    partnerMap: map,
    partnerMapHasFittedPins: false,
    percentToPartnerLatLng(x, y) {
      return { x, y };
    },
    L: {
      divIcon(options) {
        return options;
      },
      marker(location, options) {
        return {
          location,
          options,
          handlers: {},
          addTo(layer) {
            layer.markers.push(this);
            return this;
          },
          bindTooltip(content) {
            this.tooltip = content;
            return this;
          },
          on(name, handler) {
            this.handlers[name] = handler;
            return this;
          },
        };
      },
      latLngBounds(locations) {
        return locations;
      },
    },
    escapePartnerHtml(value) {
      return String(value).replace(/[&<>"']/g, (character) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character]);
    },
    renderGrid() {},
    modalScrollY: 0,
    modalBodyStyles: null,
    window: {
      scrollY: 125,
      scrollTo(_x, y) {
        this.scrollY = y;
      },
    },
    Number,
  };
  vm.createContext(sandbox);
  vm.runInContext(
    [
      extractFunction("renderGrid"),
      extractFunction("renderPins"),
      extractFunction("filterPartners"),
      extractFunction("renderCategoryFilters"),
      extractFunction("openModal"),
      extractFunction("closeModal"),
    ].join("\n"),
    sandbox,
  );
  return { elements, filterButtons, partners, partnerPinLayer, sandbox };
}

function generatedPins(pinsHtml) {
  return [...pinsHtml.matchAll(/<div class="map-pin"([^>]*)>/g)].map(
    (match) => match[1],
  );
}

function generatedPinIds(pinsHtml) {
  return [...pinsHtml.matchAll(/onclick="openModal\('([^']+)'\)"/g)].map(
    (match) => match[1],
  );
}

function assertModalMatchesPartner(elements, partner) {
  assert.equal(elements["modal-name"].textContent, partner.name);
  assert.equal(elements["modal-category"].textContent, {
    hair: "美容",
    hotel: "ホテル",
  }[partner.cat]);
  assert.equal(elements["modal-area"].textContent, `📍 ${partner.area}`);
  assert.equal(elements["modal-desc"].textContent, partner.desc);
  assert.equal(elements["modal-point"].textContent, String(partner.point));
  assert.equal(
    elements["modal-point-courses-text"].textContent,
    partner.point_courses || "",
  );
  assert.equal(
    elements["modal-point-courses"].style.display,
    partner.point_courses ? "block" : "none",
  );
  assert.ok(elements["modal-overlay"].classList.contains("open"));
}

test("clicking each map marker opens the detail for the represented partner", () => {
  const { elements, partners, partnerPinLayer, sandbox } = makeMapHarness();

  sandbox.renderPins();

  const markers = partnerPinLayer.markers;
  assert.equal(markers.length, partners.length);
  assert.deepEqual(
    markers.map((marker) => marker.options.title),
    partners.map((partner) => `${partner.name}の詳細を表示`),
  );

  for (const [index, marker] of markers.entries()) {
    marker.handlers.click();
    assertModalMatchesPartner(elements, partners[index]);
    sandbox.closeModal();
  }
});

test("eligible Nexus Point courses appear on the public partner card", () => {
  const { elements, sandbox } = makeMapHarness();

  sandbox.renderGrid();

  assert.match(elements["partners-grid"].innerHTML, /NEXUS POINT 利用可能コース/);
  assert.match(elements["partners-grid"].innerHTML, /通常カット/);
  assert.match(elements["partners-grid"].innerHTML, /カラーコース/);
  assert.match(
    partnersHtml,
    /\.point-course-text\s*\{[^}]*white-space:\s*pre-line/,
    "line breaks entered by an admin should stay readable",
  );
});

test("custom genres are available as public filters", () => {
  const { elements, sandbox } = makeMapHarness();

  sandbox.renderCategoryFilters([
    { id: "eyebrow", label: "眉毛" },
    { id: "custom_nails", label: "ネイル" },
  ]);

  const nailFilter = elements["filter-bar"].children.find(
    (button) => button.textContent === "ネイル",
  );
  assert.ok(nailFilter, "the custom genre should be rendered as a filter");
  assert.equal(nailFilter.attributes["aria-pressed"], "false");

  nailFilter.dispatch("click");

  assert.equal(sandbox.activeFilter, "custom_nails");
  assert.equal(nailFilter.attributes["aria-pressed"], "true");
  assert.ok(nailFilter.classList.contains("active"));
});

test("partners at the same coordinates remain separate clickable map markers", () => {
  const { elements, partners, partnerPinLayer, sandbox } = makeMapHarness();

  sandbox.renderPins();

  const overlappingPartners = partners.filter(
    (partner) => partner.x === 20 && partner.y === 30,
  );
  const overlappingMarkers = partnerPinLayer.markers.filter(
    (marker) => marker.location.x === 20 && marker.location.y === 30,
  );

  assert.ok(
    overlappingMarkers.length >= 3,
    "the test should cover groups of at least three partners at one location",
  );
  assert.equal(
    new Set(overlappingMarkers).size,
    overlappingPartners.length,
    "each partner at the same location should have its own marker",
  );

  for (const partner of overlappingPartners) {
    const marker = overlappingMarkers.find(
      (candidate) => candidate.options.title === `${partner.name}の詳細を表示`,
    );
    assert.ok(marker, `${partner.name} should have a clickable marker`);
    marker.handlers.click();
    assertModalMatchesPartner(elements, partner);
    sandbox.closeModal();
  }
});

test("each pin in a group of three or more at one location opens its detail by keyboard", () => {
  const { elements, partners, partnerPinLayer, sandbox } = makeMapHarness();

  sandbox.renderPins();
  const markers = partnerPinLayer.markers;
  assert.equal(markers.length, partners.length);
  const overlappingPartners = partners.filter(
    (partner) => partner.x === 20 && partner.y === 30,
  );
  assert.ok(
    overlappingPartners.length >= 3,
    "the keyboard test should cover at least three partners at one location",
  );

  for (const [index, marker] of markers.entries()) {
    const partner = partners[index];
    assert.equal(marker.options.keyboard, true);
    assert.equal(typeof marker.handlers.keydown, "function");
    for (const key of ["Enter", " "]) {
      let preventedDefault = false;
      marker.handlers.keydown({
        originalEvent: {
          key,
          preventDefault() {
            preventedDefault = true;
          },
        },
      });

      assert.equal(preventedDefault, true, `${key} should not scroll the page`);
      assertModalMatchesPartner(elements, partner);
      sandbox.closeModal();
    }
  }
});

test("category filtering keeps each generated pin connected to its own detail", () => {
  const { elements, filterButtons, partners, partnerPinLayer, sandbox } = makeMapHarness();
  const hotel = partners.find((partner) => partner.cat === "hotel");

  sandbox.filterPartners("hotel", filterButtons[0]);

  const markers = partnerPinLayer.markers;
  assert.equal(markers.length, partners.length);
  assert.ok(
    markers.find((marker) => marker.options.title === "栄ヘアサロンの詳細を表示")
      .options.icon.className.includes("dimmed"),
    "pins outside the selected category should be visibly dimmed",
  );
  assert.equal(
    markers.find((marker) => marker.options.title === `${hotel.name}の詳細を表示`)
      .options.icon.className.includes("dimmed"),
    false,
  );
  assert.ok(filterButtons[0].classList.contains("active"));
  assert.equal(filterButtons[0].attributes["aria-pressed"], "true");

  const targetMarker = markers.find(
    (marker) => marker.options.title === `${hotel.name}の詳細を表示`,
  );
  assert.ok(targetMarker, "the filtered category's partner pin should exist");
  targetMarker.handlers.click();
  assertModalMatchesPartner(elements, hotel);
});
