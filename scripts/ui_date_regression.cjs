// Run with Playwright and Flatpickr available in NODE_PATH (no database needed).
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
    const browser = await chromium.launch({headless: true,
        ...(process.env.CHROME_PATH ? {executablePath: process.env.CHROME_PATH} : {})});
    try {
        const page = await browser.newPage();
        await page.setContent('<input id="meetDate" class="date-picker" value="07.09.2026"><input id="nativeDate" type="date"><input id="password" type="password">');
        await page.addScriptTag({path: require.resolve('flatpickr')});
        await page.addScriptTag({path: path.resolve(__dirname, '../static/ui_enhancements.js')});
        await page.evaluate(() => {
            window.dateChanges = 0;
            flatpickr('#meetDate', {dateFormat: 'd.m.Y', disableMobile: true,
                onChange: () => window.dateChanges++});
            window.refreshUniversalUiEnhancements();
        });
        assert.equal(await page.locator('.ui-date-field').count(), 1, 'Enhancement must be idempotent');
        assert.equal(await page.locator('#nativeDate').getAttribute('type'), 'date');
        await page.locator('.ui-date-field__button').click();
        assert.equal(await page.evaluate(() => document.querySelector('#meetDate')._flatpickr.isOpen), true,
            'Calendar icon must open the existing Flatpickr even when it makes the input readonly');
        await page.evaluate(() => {
            const picker = document.querySelector('.ui-date-field__native');
            picker.value = '2026-09-15';
            picker.dispatchEvent(new Event('change', {bubbles:true}));
        });
        assert.equal(await page.locator('#meetDate').inputValue(), '15.09.2026');
        assert.equal(await page.evaluate(() => window.dateChanges), 1, 'Existing onChange must run exactly once');
        await page.evaluate(() => {document.querySelector('#meetDate').disabled = true;});
        await page.waitForFunction(() => document.querySelector('.ui-date-field__button').disabled);
        await page.evaluate(() => {
            const input = document.querySelector('#meetDate');
            input.disabled = false;
            input._flatpickr.destroy();
            input.readOnly = true;
        });
        await page.waitForFunction(() => document.querySelector('.ui-date-field__button').disabled);
        await page.evaluate(() => {document.querySelector('#meetDate').readOnly = false;});
        await page.waitForFunction(() => !document.querySelector('.ui-date-field__button').disabled);
        await page.evaluate(() => {
            const picker = document.querySelector('.ui-date-field__native');
            picker.value = '2026-12-31';
            picker.dispatchEvent(new Event('change', {bubbles:true}));
        });
        assert.equal(await page.locator('#meetDate').inputValue(), '31.12.2026', 'Native fallback must preserve Russian date format');
        console.log('PASS: existing calendar, callbacks, disabled/readonly, native fallback, idempotency');
    } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
