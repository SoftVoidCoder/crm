// Run with Playwright in NODE_PATH; requests are fixtures and never reach a database.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try {
  const page=await browser.newPage();
  await page.setContent(`<div id="bitrixConnectionPanel"><div id="bitrixConnectionStatus"></div><details id="bitrixConnectionSettings"><input id="bitrixWebhookInput"></details></div><div id="outreachBitrixStatus"></div><div id="outreachBitrixResults"></div><input id="outreachBitrixSearch"><button id="outreachBitrixSearchButton"></button><button id="outreachBitrixImportButton"></button><div id="outreachPoolMount"></div><div id="bitrixImportStats"></div>`);
  await page.evaluate(()=>{
   window.currentUser={role:'Менеджер'};
   window.hasCurrentPermission=(module,action)=>module==='clients'&&action==='read';
   window.response={status:'success',configured:true,portal:'https://example.bitrix24.ru'};
   window.apiCall=async()=>window.response;
   window.showToast=()=>{};
   window.customAlert=()=>{};
  });
  await page.addScriptTag({path:path.resolve(__dirname,'../static/prospecting.js')});
  assert(await page.evaluate(()=>canUseBitrixImport()),'Match server access rules for managers with client read permission');
  await page.evaluate(()=>loadBitrixConnectionStatus());
  assert.match(await page.locator('#bitrixConnectionStatus').innerText(),/Подключено/);
  assert.equal(await page.locator('#outreachBitrixStatus a').getAttribute('href'),'https://example.bitrix24.ru');
  assert.equal(await page.locator('#outreachBitrixSearchButton').isDisabled(),false);
  await page.evaluate(()=>{window.response={error:'network_error'};});
  await page.evaluate(()=>loadBitrixConnectionStatus());
  assert.match(await page.locator('#bitrixConnectionStatus').innerText(),/Статус не обновлён/);
  assert.doesNotMatch(await page.locator('#bitrixConnectionStatus').innerText(),/Не подключено/);
  assert.equal(await page.locator('#outreachBitrixStatus a').count(),1,'Keep known portal during temporary failures');
  assert.equal(await page.locator('#outreachBitrixSearchButton').isDisabled(),false);
  await page.evaluate(()=>{outreachBitrixConnection=null;});
  await page.evaluate(()=>loadBitrixConnectionStatus());
  assert.doesNotMatch(await page.locator('#bitrixConnectionStatus').innerText(),/Не подключено/,'Initial request failure is unknown, not disconnected');
  await page.evaluate(()=>{window.response={status:'success',configured:false,portal:''};});
  await page.evaluate(()=>loadBitrixConnectionStatus());
  assert.match(await page.locator('#bitrixConnectionStatus').innerText(),/Не подключено/);
  await page.evaluate(()=>{window.response={status:'success',configured:true,portal:'https://example.bitrix24.ru'};});
  await page.evaluate(()=>loadBitrixConnectionStatus());
  await page.evaluate(()=>{window.response={status:'success',items:[{type:'company',id:'15',title:'Тестовый клиент'}]};});
  await page.locator('#outreachBitrixSearch').fill('Тестовый');
  await page.evaluate(()=>searchBitrixClients());
  assert.equal(await page.locator('#outreachBitrixResults input[type=checkbox]').count(),1);
  assert.equal(await page.locator('#outreachBitrixImportButton').isDisabled(),false);
  await page.locator('#outreachBitrixResults input[type=checkbox]').uncheck();
  assert.equal(await page.locator('#outreachBitrixImportButton').isDisabled(),true);
  await page.locator('#outreachBitrixResults input[type=checkbox]').check();
  assert.equal(await page.locator('#outreachBitrixImportButton').isDisabled(),false);
  await page.evaluate(()=>{outreachPoolRows=[{id:1,company_name:'Клиент'}];window.response={error:'network_error'};});
  await page.evaluate(()=>refreshOutreachPool(false));
  assert.equal(await page.evaluate(()=>outreachPoolRows.length),1,'Temporary refresh errors must not erase loaded clients');
  await page.evaluate(()=>{window.response=[{source_name:'Bitrix24 API',phone:'123'}];});
  await page.evaluate(()=>loadBitrixImportRows());
  await page.evaluate(()=>{outreachProspectsDB=[];renderBitrixImportStats();});
  assert.equal(await page.locator('#bitrixImportStats .crm-summary-value').first().innerText(),'1','Personal client scope must not reset Bitrix totals');
  console.log('PASS: manager permissions, saved portal link, error/retry/disconnected states, client selection, pool retention');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
