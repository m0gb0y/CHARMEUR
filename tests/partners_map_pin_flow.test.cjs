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
}

function makeMapHarness() {
  const ids = [
    "map-wrapper",
    "map-pins",
    "map-legend",
    "modal-letter",
    "modal-category",
    "modal-name",
    "modal-area",
    "modal-desc",
    "modal-point",
    "modal-photo",
    "modal-stylist",
    "modal-btn",
    "modal-coming-soon",
    "modal-overlay",
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, new FakeElement()]));
  const filterButtons = [new FakeElement(), new FakeElement()];
  const partners = [
    {
      id: "hair-partner-id",
      marker: "01",
      name: "栄ヘアサロン",
      cat: "hair",
      area: "名古屋市中区",
      desc: "ヘアサロンの詳細",
      point: 120,
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
      photo: "",
      url: "https://example.com/same-location",
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
      getElementById(id) {
        return elements[id];
      },
      querySelectorAll(selector) {
        assert.equal(selector, ".filter-btn");
        return filterButtons;
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
    Number,
  };
  vm.createContext(sandbox);
  vm.runInContext(
    [
      extractFunction("renderPins"),
      extractFunction("filterPartners"),
      extractFunction("openModal"),
    ].join("\n"),
    sandbox,
  );
  return { elements, filterButtons, partners, sandbox };
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
  assert.ok(elements["modal-overlay"].classList.contains("open"));
}

test("clicking each map pin opens the detail for the partner represented by that pin", () => {
  const { elements, partners, sandbox } = makeMapHarness();

  sandbox.renderPins();
  const pinIds = generatedPinIds(elements["map-pins"].innerHTML);
  assert.deepEqual(pinIds, partners.map((partner) => partner.id));

  for (const pinId of pinIds) {
    sandbox.openModal(pinId);
    const partner = partners.find((entry) => entry.id === pinId);
    assertModalMatchesPartner(elements, partner);
  }
});

test("partners at the same coordinates have separate selectable pins", () => {
  const { elements, partners, sandbox } = makeMapHarness();

  sandbox.renderPins();

  const pinAttributes = generatedPins(elements["map-pins"].innerHTML);
  const pinIds = generatedPinIds(elements["map-pins"].innerHTML);
  const overlappingPartners = partners.filter(
    (partner) => partner.x === 20 && partner.y === 30,
  );
  const overlappingPins = overlappingPartners.map((partner) => {
    const index = pinIds.indexOf(partner.id);
    assert.notEqual(index, -1, `${partner.name} should have a map pin`);
    return pinAttributes[index];
  });
  const transforms = overlappingPins.map(
    (attributes) => attributes.match(/transform:([^;"]+)/)?.[1],
  );

  assert.equal(overlappingPins.length, 2);
  assert.ok(
    transforms.every(Boolean),
    "pins sharing a location should each be offset from the exact same point",
  );
  assert.notEqual(transforms[0], transforms[1]);

  for (const partner of overlappingPartners) {
    sandbox.openModal(partner.id);
    assertModalMatchesPartner(elements, partner);
  }
});

test("map pins are keyboard-focusable and Enter or Space opens the matching detail", () => {
  const { elements, partners, sandbox } = makeMapHarness();

  sandbox.renderPins();
  const pins = generatedPins(elements["map-pins"].innerHTML);
  assert.equal(pins.length, partners.length);

  for (const [index, pinAttributes] of pins.entries()) {
    const partner = partners[index];
    assert.match(pinAttributes, /role="button"/);
    assert.match(pinAttributes, /tabindex="0"/);
    assert.match(
      pinAttributes,
      new RegExp(`aria-label="${partner.name}の詳細を表示"`),
    );

    const keydownHandler = pinAttributes.match(/onkeydown="([^"]+)"/)?.[1];
    assert.ok(keydownHandler, "each pin should handle keyboard activation");

    for (const key of ["Enter", " "]) {
      let preventedDefault = false;
      sandbox.event = {
        key,
        preventDefault() {
          preventedDefault = true;
        },
      };
      vm.runInContext(keydownHandler, sandbox);

      assert.equal(preventedDefault, true, `${key} should not scroll the page`);
      assertModalMatchesPartner(elements, partner);
      elements["modal-overlay"].classList.remove("open");
    }
  }
});

test("category filtering keeps each generated pin connected to its own detail", () => {
  const { elements, filterButtons, partners, sandbox } = makeMapHarness();
  const hotel = partners.find((partner) => partner.cat === "hotel");

  sandbox.filterPartners("hotel", filterButtons[0]);

  const pinIds = generatedPinIds(elements["map-pins"].innerHTML);
  assert.deepEqual(pinIds, partners.map((partner) => partner.id));
  assert.match(
    elements["map-pins"].innerHTML,
    /map-pin-dot dimmed[^>]*>01<\/div>/,
    "pins outside the selected category should be visibly dimmed",
  );
  assert.ok(filterButtons[0].classList.contains("active"));

  const targetPinId = pinIds.find((id) => id === hotel.id);
  assert.ok(targetPinId, "the filtered category's partner pin should exist");
  sandbox.openModal(targetPinId);
  assertModalMatchesPartner(elements, hotel);
});
