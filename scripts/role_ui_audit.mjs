import { createRequire } from "node:module";
import fs from "node:fs/promises";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const [
  baseUrl,
  acceptanceReport,
  password,
  outputDir = "/tmp/korda-role-ui-audit",
] = process.argv.slice(2);

if (!baseUrl || !acceptanceReport || !password) {
  throw new Error(
    "Usage: role_ui_audit.mjs <base-url> <acceptance-report.json> <password> [output-dir]",
  );
}

const report = JSON.parse(await fs.readFile(acceptanceReport, "utf8"));
const roleUsers = Object.values(report.users || {});
if (!roleUsers.length) throw new Error("Acceptance report does not contain role users");

await fs.mkdir(outputDir, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});

const technicalEnglishPattern = new RegExp(
  [
    "\\berrors?\\b",
    "\\bretryable\\b",
    "\\bidempotency\\b",
    "\\bcollisions?\\b",
    "\\bconsistency\\b",
    "\\bobject identifier\\b",
    "\\bitem (?:name|article)\\b",
    "\\bexpected date\\b",
    "\\bcontract identifier\\b",
    "\\bproduction open\\b",
  ].join("|"),
  "gi",
);

const slug = (value) => String(value || "")
  .toLowerCase()
  .normalize("NFKD")
  .replace(/[^a-z0-9а-яё]+/gi, "-")
  .replace(/^-+|-+$/g, "");

const results = [];

try {
  for (const roleUser of roleUsers) {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
      deviceScaleFactor: 1,
      locale: "ru-RU",
    });
    const page = await context.newPage();
    const runtimeErrors = [];
    const failedApiResponses = [];

    page.on("pageerror", (error) => runtimeErrors.push(String(error.message || error)));
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) {
        failedApiResponses.push({
          status: response.status(),
          url: response.url().replace(baseUrl, ""),
        });
      }
    });

    await page.goto(`${baseUrl}/static/login.html`, { waitUntil: "domcontentloaded" });
    await page.fill("#loginEmail", roleUser.email);
    await page.fill("#loginPassword", password);
    await page.click('button:has-text("Войти")');
    await page.waitForURL("**/app", { timeout: 20_000 });
    await page.waitForTimeout(1_500);

    const visibleNavigation = await page.evaluate(() => (
      [...document.querySelectorAll(".sidebar .nav-item[id]")]
        .filter((element) => (
          element.id !== "navMobileScanner"
          && element.offsetParent !== null
          && getComputedStyle(element).display !== "none"
        ))
        .map((element) => {
          const onclick = String(element.getAttribute("onclick") || "");
          const match = onclick.match(/navigateTo\(['"]([^'"]+)['"]\)/);
          return {
            id: element.id,
            label: String(element.innerText || "").trim().replace(/\s+/g, " "),
            view: match ? match[1] : "",
          };
        })
        .filter((item) => item.view)
    ));

    const roleResult = {
      role: roleUser.role,
      name: roleUser.name,
      visibleNavigation,
      views: [],
      unexpectedDialogs: [],
      runtimeErrors,
      failedApiResponses,
    };

    for (const navigation of visibleNavigation) {
      await page.evaluate((view) => window.navigateTo(view), navigation.view);
      await page.waitForTimeout(500);

      const metrics = await page.evaluate(({ expectedView, englishSource }) => {
        const active = [...document.querySelectorAll(".view-page")]
          .find((element) => element.offsetParent !== null);
        const viewportWidth = document.documentElement.clientWidth;
        const activeText = String(active?.innerText || "").replace(/\s+/g, " ").trim();
        const englishPattern = new RegExp(englishSource, "gi");
        const technicalEnglish = [...new Set(activeText.match(englishPattern) || [])];
        const overflow = Math.max(0, document.documentElement.scrollWidth - viewportWidth);
        const emptyState = !active || activeText.length < 5;
        return {
          expectedView,
          activeView: active?.id || "",
          bodyRole: document.body.dataset.roleName || "",
          rootOverflow: overflow,
          technicalEnglish,
          emptyState,
          title: String(active?.querySelector("h1,h2,.view-title")?.textContent || "")
            .trim()
            .replace(/\s+/g, " ")
            .slice(0, 140),
          dialog: (() => {
            const modal = document.getElementById("genericModal");
            if (!modal || modal.offsetParent === null || getComputedStyle(modal).display === "none") {
              return "";
            }
            return String(document.getElementById("genModalBody")?.innerText || "")
              .trim()
              .replace(/\s+/g, " ")
              .slice(0, 300);
          })(),
        };
      }, {
        expectedView: navigation.view,
        englishSource: technicalEnglishPattern.source,
      });

      roleResult.views.push({
        navigation: navigation.label,
        view: navigation.view,
        ...metrics,
      });
      if (metrics.dialog) {
        roleResult.unexpectedDialogs.push({
          navigation: navigation.label,
          view: navigation.view,
          message: metrics.dialog,
        });
        await page.locator("#genOk, #genCancel").first().click().catch(() => {});
      }
    }

    const roleSlug = slug(roleUser.role) || "role";
    await page.screenshot({
      path: path.join(outputDir, `${roleSlug}.png`),
      fullPage: false,
    });

    roleResult.runtimeErrors = [...new Set(runtimeErrors)];
    roleResult.failedApiResponses = [
      ...new Map(failedApiResponses.map((item) => [`${item.status}:${item.url}`, item])).values(),
    ];
    roleResult.passed = (
      roleResult.views.length > 0
      && roleResult.views.every((view) => (
        !view.emptyState
        && view.rootOverflow <= 4
        && view.technicalEnglish.length === 0
        && view.bodyRole === roleUser.role
      ))
      && roleResult.runtimeErrors.length === 0
      && roleResult.unexpectedDialogs.length === 0
    );
    results.push(roleResult);
    await context.close();
  }
} finally {
  await browser.close();
}

const summary = {
  marker: report.marker,
  generatedAt: new Date().toISOString(),
  roles: results.length,
  views: results.reduce((total, role) => total + role.views.length, 0),
  passedRoles: results.filter((role) => role.passed).length,
  failedRoles: results.filter((role) => !role.passed).map((role) => role.role),
  issues: results.flatMap((role) => role.views
    .filter((view) => (
      view.emptyState
      || view.rootOverflow > 4
      || view.technicalEnglish.length > 0
      || view.bodyRole !== role.role
    ))
    .map((view) => ({
      role: role.role,
      navigation: view.navigation,
      view: view.view,
      activeView: view.activeView,
      emptyState: view.emptyState,
      rootOverflow: view.rootOverflow,
      technicalEnglish: view.technicalEnglish,
      bodyRole: view.bodyRole,
    }))),
  runtimeErrors: results.flatMap((role) => role.runtimeErrors.map((error) => ({
    role: role.role,
    error,
  }))),
  failedApiResponses: results.flatMap((role) => role.failedApiResponses.map((response) => ({
    role: role.role,
    ...response,
  }))),
  unexpectedDialogs: results.flatMap((role) => role.unexpectedDialogs.map((dialog) => ({
    role: role.role,
    ...dialog,
  }))),
  results,
};

await fs.writeFile(
  path.join(outputDir, "role-ui-audit.json"),
  JSON.stringify(summary, null, 2),
);

const markdown = [
  `# UI-аудит ролей: ${report.marker}`,
  "",
  `- Ролей: ${summary.roles}`,
  `- Открыто экранов: ${summary.views}`,
  `- Ролей без визуальных ошибок: ${summary.passedRoles}`,
  `- Проблемных экранов: ${summary.issues.length}`,
  `- Ошибок JavaScript: ${summary.runtimeErrors.length}`,
  "",
  "## Роли",
  "",
  ...results.map((role) => (
    `- ${role.passed ? "[x]" : "[ ]"} ${role.role}: ${role.views.length} экранов`
  )),
];

if (summary.issues.length) {
  markdown.push("", "## Найденные проблемы", "");
  for (const issue of summary.issues) {
    markdown.push(
      `- ${issue.role} / ${issue.navigation}: overflow=${issue.rootOverflow}, `
      + `empty=${issue.emptyState}, english=${issue.technicalEnglish.join(", ") || "нет"}`,
    );
  }
}

if (summary.runtimeErrors.length) {
  markdown.push("", "## Ошибки JavaScript", "");
  for (const item of summary.runtimeErrors) {
    markdown.push(`- ${item.role}: ${item.error}`);
  }
}

if (summary.unexpectedDialogs.length) {
  markdown.push("", "## Неожиданные уведомления", "");
  for (const item of summary.unexpectedDialogs) {
    markdown.push(`- ${item.role} / ${item.navigation}: ${item.message}`);
  }
}

await fs.writeFile(path.join(outputDir, "role-ui-audit.md"), `${markdown.join("\n")}\n`);
console.log(JSON.stringify({
  outputDir,
  roles: summary.roles,
  views: summary.views,
  passedRoles: summary.passedRoles,
  issues: summary.issues.length,
  runtimeErrors: summary.runtimeErrors.length,
  failedApiResponses: summary.failedApiResponses.length,
  unexpectedDialogs: summary.unexpectedDialogs.length,
}, null, 2));
