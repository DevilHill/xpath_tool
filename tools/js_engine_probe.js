/* 在 Node + jsdom 中运行扩展的 JS 定位引擎，输出 JSON 结果供比对。
 *
 * 用法：node tools/js_engine_probe.js <html文件路径>
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const ENGINE_SRC = fs.readFileSync(path.join(ROOT, "extension", "lib", "engine.js"), "utf8");

const htmlPath = process.argv[2];
if (!htmlPath) {
  console.error("用法: node tools/js_engine_probe.js <html文件>");
  process.exit(1);
}
const html = fs.readFileSync(htmlPath, "utf8");

const dom = new JSDOM(html);
global.window = dom.window;
global.document = dom.window.document;
global.XPathResult = dom.window.XPathResult;
global.CSS = dom.window.CSS;
global.Node = dom.window.Node;

// 载入引擎（IIFE 会挂到 window 上）
// eslint-disable-next-line no-eval
eval(ENGINE_SRC);
const E = dom.window.XPathStudioEngine;

function pick(sel) {
  return dom.window.document.querySelector(sel);
}

function slim(c) {
  return { xpath: c.xpath, strategy: c.strategy, count: c.count, unique: c.unique, score: c.score, level: c.level };
}

const result = { gen: {}, errors: [] };

const targets = {
  "#login-btn": "#login-btn",
  ".add-to-cart": ".add-to-cart",
  "[id^='j_idt']": "[id^='j_idt']",
  "#username": "#username",
  ".cart-link": ".cart-link",
  ".product-title": ".product-title",
  "[name=phone]": "[name='phone']",
  "[data-testid]": "[data-testid]",
  "#email": "#email"
};

for (const key of Object.keys(targets)) {
  const el = pick(targets[key]);
  if (!el) { result.errors.push("未找到元素 " + key); continue; }
  try {
    const r = E.genForElement(el);
    result.gen[key] = {
      best: r.best,
      css: r.css,
      playwright: r.playwright.map(p => p.code),
      candidates: r.xpath.map(slim),
      targetTag: r.target.tag,
      dynamicId: r.target.dynamicId
    };
  } catch (e) {
    result.errors.push("gen " + key + " 抛异常: " + e.message);
  }
}

try {
  result.scan = E.scanPage().map(i => ({ xpath: i.xpath, score: i.score, tag: i.tag }));
} catch (e) {
  result.errors.push("scan 抛异常: " + e.message);
}

try {
  result.verify = E.verifyBatch([
    "//button[@id='login-btn']",
    ".add-to-cart",
    "//div[@id='nope']",
    "#login-form input[name='username']",
    "//a[@href='/cart']"
  ]).map(r => ({ selector: r.selector, type: r.type, valid: r.valid, count: r.count }));
} catch (e) {
  result.errors.push("verify 抛异常: " + e.message);
}

try {
  const v = E.validate("//button[@id='login-btn']");
  result.validate = { valid: v.valid, count: v.count };
  const bad = E.validate("//div[@@bad");
  result.validateBad = { valid: bad.valid, error: bad.error };
  result.minimalLoginBtn = E.minimalXPath(pick("#login-btn"))[0];
  result.absoluteLoginBtn = E.absoluteXPath(pick("#login-btn"));
} catch (e) {
  result.errors.push("validate 抛异常: " + e.message);
}

// 自愈建议（对着改版后的选择器）
try {
  const HEAL_SELECTORS = [
    "//button[@id='login-btn-v2']",
    "//a[contains(concat(' ', normalize-space(@class), ' '), ' cart-link-old ')]",
    "//input[@name='user_name']",
    ".add-to-cart-legacy",
    "//button[normalize-space(text())='登 录一下']",
    "//div[@class='totally-absent']"
  ];
  result.heal = E.verifyBatch(HEAL_SELECTORS).map(function (r) {
    return {
      selector: r.selector,
      count: r.count,
      heal: (r.heal || []).map(function (h) {
        return [h.xpath, h.score, h.confidence, h.reason];
      })
    };
  });
  result.healPure = {
    simLoginBtn: Math.round(E.similarText("login-btn", "login-button") * 1000) / 1000,
    simRegister: Math.round(E.similarText("login-btn", "register-btn") * 1000) / 1000,
    simCjk: Math.round(E.similarText("登录", "立即登录") * 1000) / 1000,
    simCjkSpace: Math.round(E.similarText("登录", "登 录") * 1000) / 1000,
    hints: E.parseSelectorHints("//a[contains(concat(' ', normalize-space(@class), ' '), ' cart-link ')]"),
    cssHints: E.parseCssHints("#login-btn .cart-link")
  };
} catch (e) {
  result.errors.push("heal 抛异常: " + e.message);
}

// 纯函数单元测试
try {
  result.pure = {
    dynamic: [
      E.isDynamicValue("j_idt88")[0],
      E.isDynamicValue("A1001")[0],
      E.isDynamicValue("sc-bdVTJa")[0],
      E.isDynamicValue("login-btn")[0],
      E.isDynamicValue("550e8400-e29b-41d4-a716-446655440000")[0]
    ],
    dynamic2: [
      E.isDynamicValue("_ngcontent-c0")[0],
      E.isDynamicValue("_nghost-c1")[0],
      E.isDynamicValue(":r1a:")[0],
      E.isDynamicValue("12345")[0],
      E.isDynamicValue("ember482")[0],
      E.isDynamicValue("username")[0]
    ],
    classes: E.stableClassTokens("btn btn-primary active hover is-open"),
    classesHash: E.stableClassTokens("sc-bdVTJa dKpMkN"),
    hashy: [
      E.isHashyToken("dKpMkN"), E.isHashyToken("sc-bdVaJa"), E.isHashyToken("css-1q2w3e"),
      E.isHashyToken("svelte-1a2b3c"), E.isHashyToken("bg-red-500"), E.isHashyToken("text-2xl"),
      E.isHashyToken("rounded-full"), E.isHashyToken("container"), E.isHashyToken("grid-cols-3")
    ],
    classesTailwind: E.stableClassTokens("bg-red-500 hover:bg-red-600 text-2xl rounded-full btn-primary"),
    labelText: [E.labelTextFor(pick("#email")), E.labelTextFor(pick("[name='phone']"))],
    labelAnchors: E.labelAnchoredXpaths(pick("[name='phone']")).map(function (a) { return a[0]; }),
    testidCands: E.genForElement(pick("[data-testid]")).xpath
      .filter(function (c) { return c.strategy === "testid"; })
      .map(function (c) { return [c.xpath, c.score, c.unique]; }),
    label: [E.stabilityLabel(88), E.stabilityLabel(60), E.stabilityLabel(20)],
    literal: [E.xpathLiteral("a'b"), E.xpathLiteral('a"b'), E.xpathLiteral("a'b\"c")]
  };
} catch (e) {
  result.errors.push("pure 抛异常: " + e.message);
}

process.stdout.write(JSON.stringify(result, null, 2));
