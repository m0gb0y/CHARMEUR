const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const adminHtml = fs.readFileSync(
  path.join(__dirname, "..", "admin.html"),
  "utf8",
);
const [, adminScript] = adminHtml.match(/<script>([\s\S]*?)<\/script>/) || [];
assert.ok(adminScript, "admin.html must contain its admin script");

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(value) {
    this.values.add(value);
  }

  remove(value) {
    this.values.delete(value);
  }

  contains(value) {
    return this.values.has(value);
  }
}

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this._value = "";
    this.files = [];
    this.checked = false;
    this.disabled = false;
    this.textContent = "";
    this.className = "";
    this.classList = new FakeClassList();
    this.style = {};
    this.children = [];
    this.listeners = new Map();
    this.attributes = {};
  }

  get value() {
    return this._value;
  }

  set value(value) {
    this._value = value == null ? "" : String(value);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatch(type, event = {}) {
    let result;
    for (const listener of this.listeners.get(type) || []) {
      result = listener(event);
    }
    return result;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = [...children];
  }

  removeAttribute(name) {
    delete this.attributes[name];
    if (name === "src") this.src = "";
  }

  focus() {}

  getBoundingClientRect() {
    return { left: 0, top: 0, width: 100, height: 100 };
  }

  setPointerCapture() {}

  reset() {
    for (const element of elements.values()) {
      element.value = "";
      element.files = [];
      element.checked = false;
    }
  }
}

const existingImageUrl =
  "/uploads/partners/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.jpg";
const existingPartner = {
  id: "partner-1",
  name: "テスト提携先",
  category: "hair",
  area: "名古屋市",
  description: "",
  website_url: "",
  image_url: existingImageUrl,
  nexus_points: 0,
  map_x: null,
  map_y: null,
  published: true,
  display_order: 1,
};

function createAdminPage() {
  const elements = new Map();
  const getElementById = (id) => {
    if (!elements.has(id)) elements.set(id, new FakeElement(id));
    return elements.get(id);
  };
  const requests = [];
  const objectUrls = [];
  const revokedObjectUrls = [];

  class FakeFormData {
    constructor() {
      this.entries = [];
    }

    append(...entry) {
      this.entries.push(entry);
    }
  }

  const context = {
    document: {
      getElementById,
      createElement: (tagName) => new FakeElement(tagName),
    },
    window: { scrollTo() {}, confirm: () => true },
    URL: {
      createObjectURL(file) {
        const url = `blob:preview-${file.name}`;
        objectUrls.push({ file, url });
        return url;
      },
      revokeObjectURL(url) {
        revokedObjectUrls.push(url);
      },
    },
    FormData: FakeFormData,
    fetch: async (url, options = {}) => {
      requests.push({ url, options });
      let body = {};
      if (url === "/api/admin/session") {
        body = { authenticated: true };
      } else if (url === "/api/admin/partners") {
        body = { partners: [existingPartner] };
      } else if (url === `/api/admin/partners/${existingPartner.id}`) {
        body = { partner: { ...existingPartner } };
      }
      return { ok: true, json: async () => body };
    },
    console,
  };

  vm.runInNewContext(adminScript, context, { filename: "admin.html" });
  return {
    elements,
    getElementById,
    requests,
    objectUrls,
    revokedObjectUrls,
  };
}

async function waitForDashboard(page) {
  for (let attempt = 0; attempt < 10; attempt += 1) {
    if (page.getElementById("partner-list").children.length) return;
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.fail("admin page did not load its partner list");
}

test("choosing a new image shows its local preview before saving", () => {
  const page = createAdminPage();
  const fileInput = page.getElementById("image-file");
  const preview = page.getElementById("image-preview");
  const previewImage = page.getElementById("image-preview-image");
  const previewStatus = page.getElementById("image-preview-status");
  const selectedFile = { name: "new-partner-photo.png" };

  fileInput.files = [selectedFile];
  fileInput.dispatch("change");

  assert.equal(preview.classList.contains("hidden"), false);
  assert.equal(previewImage.src, "blob:preview-new-partner-photo.png");
  assert.match(previewStatus.textContent, /選択した画像をプレビュー中/);
  assert.deepEqual(page.objectUrls, [
    { file: selectedFile, url: "blob:preview-new-partner-photo.png" },
  ]);
});

test("editing and saving without choosing an image keeps the registered image URL", async () => {
  const page = createAdminPage();
  await waitForDashboard(page);

  const editButton = page
    .getElementById("partner-list")
    .children[0].children[1].children[0];
  editButton.dispatch("click");

  const preview = page.getElementById("image-preview");
  const previewImage = page.getElementById("image-preview-image");
  const previewStatus = page.getElementById("image-preview-status");
  assert.equal(page.getElementById("image_url").value, existingImageUrl);
  assert.deepEqual(page.getElementById("image-file").files, []);
  assert.equal(preview.classList.contains("hidden"), false);
  assert.equal(previewImage.src, existingImageUrl);
  assert.match(previewStatus.textContent, /現在の登録画像/);

  const form = page.getElementById("partner-form");
  await form.dispatch("submit", { preventDefault() {} });

  const update = page.requests.find(
    ({ url, options }) =>
      url === `/api/admin/partners/${existingPartner.id}` &&
      options.method === "PUT",
  );
  assert.ok(update, "editing should send an update request");
  assert.equal(JSON.parse(update.options.body).image_url, existingImageUrl);
  assert.equal(
    page.requests.some(({ url }) => url === "/api/admin/uploads/partner-image"),
    false,
    "saving without a newly selected image should not upload a file",
  );
});
