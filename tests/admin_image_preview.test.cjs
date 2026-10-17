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
  constructor(id = "", resetElements = () => {}) {
    this.id = id;
    this.resetElements = resetElements;
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
    this.resetElements();
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
    if (!elements.has(id)) {
      elements.set(
        id,
        new FakeElement(id, () => {
          for (const element of elements.values()) {
            element.value = "";
            element.files = [];
            element.checked = false;
          }
        }),
      );
    }
    return elements.get(id);
  };
  const requests = [];
  const objectUrls = [];
  const revokedObjectUrls = [];
  const uploadResponses = [];

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
        } else if (url === "/api/admin/uploads/partner-image") {
          const response = uploadResponses.shift() || {
            ok: true,
            body: {
              image_url:
                "/uploads/partners/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg",
            },
          };
          return { ok: response.ok, json: async () => response.body };
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
    uploadResponses,
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

test("upload rejection preserves partner details and allows retry with a replacement image", async () => {
  const page = createAdminPage();
  await waitForDashboard(page);

  const fields = {
    name: "再試行できる提携先",
    category: "wellness",
    area: "名古屋市中区",
    description: "入力した紹介文を保持します。",
    website_url: "https://example.com/partner",
    nexus_points: "250",
    map_x: "42.5",
    map_y: "61.2",
    display_order: "3",
  };
  for (const [id, value] of Object.entries(fields)) {
    page.getElementById(id).value = value;
  }
  page.getElementById("published").checked = true;

  const fileInput = page.getElementById("image-file");
  const rejectedFile = { name: "rejected.gif" };
  fileInput.files = [rejectedFile];
  page.uploadResponses.push({
    ok: false,
    body: { error: "JPEG、PNG、WebP形式の画像を選択してください。" },
  });

  const form = page.getElementById("partner-form");
  await form.dispatch("submit", { preventDefault() {} });

  const message = page.getElementById("form-message");
  const saveButton = page.getElementById("save-button");
  assert.equal(
    message.textContent,
    "JPEG、PNG、WebP形式の画像を選択してください。",
  );
  assert.equal(message.classList.contains("error"), true);
  assert.equal(saveButton.disabled, false, "saving should be available again");
  assert.deepEqual(fileInput.files, [rejectedFile]);
  for (const [id, value] of Object.entries(fields)) {
    assert.equal(page.getElementById(id).value, value, `${id} should be preserved`);
  }
  assert.equal(page.getElementById("published").checked, true);
  assert.equal(
    page.requests.some(
      ({ url, options }) =>
        options.method &&
        (url === "/api/admin/partners" ||
          url.startsWith("/api/admin/partners/")),
    ),
    false,
    "partner data should not be submitted after upload rejection",
  );

  const replacementFile = { name: "replacement.jpg" };
  fileInput.files = [replacementFile];
  fileInput.dispatch("change");
  assert.equal(
    page.getElementById("image-preview-image").src,
    "blob:preview-replacement.jpg",
    "the replacement image should be previewed before retry",
  );

  await form.dispatch("submit", { preventDefault() {} });

  const uploadRequests = page.requests.filter(
    ({ url }) => url === "/api/admin/uploads/partner-image",
  );
  assert.equal(uploadRequests.length, 2, "retry should upload the new image");
  assert.deepEqual(uploadRequests[1].options.body.entries, [
    ["image", replacementFile],
  ]);

  const createRequest = page.requests.find(
    ({ url, options }) => url === "/api/admin/partners" && options.method === "POST",
  );
  assert.ok(createRequest, "partner data should be submitted after retry succeeds");
  assert.deepEqual(JSON.parse(createRequest.options.body), {
    name: fields.name,
    category: fields.category,
    area: fields.area,
    description: fields.description,
    website_url: fields.website_url,
    image_url: "/uploads/partners/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.jpg",
    nexus_points: 250,
    map_x: fields.map_x,
    map_y: fields.map_y,
    display_order: 3,
    published: true,
  });
  assert.equal(saveButton.disabled, false);
  assert.match(message.textContent, /保存しました/);
  assert.equal(message.classList.contains("error"), false);
});
