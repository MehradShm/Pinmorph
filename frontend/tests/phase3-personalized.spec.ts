import { test, expect } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

test('Discover uses cold fallback then the activated model after a real closeup', async ({ page }) => {
  test.skip(process.env.RUN_PERSONALIZED_UI !== '1', 'Requires explicit personalized feed configuration');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const viewed = new Set<string>();
  page.on('response', response => {
    if (response.url().endsWith('/api/events') && response.status() === 200) {
      const event = response.request().postDataJSON();
      if (event?.kind === 'impression') viewed.add(event.pin_id);
    }
  });
  const email = `browser-${Date.now()}-${Math.random().toString(36).slice(2)}@example.test`;
  const response = await page.request.post('/api/auth/signup', { data: {
    email, display_name: 'Personalization tester', password: 'browser-password-123',
  } });
  expect(response.status()).toBe(201);
  const account = await response.json();
  const path = test.info().outputPath('account.json');
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify({ id: account.id, email }));
  const cold = await (await page.request.get('/api/feed')).json();
  expect(cold.config_version).toMatch(/^feed:personalized:/);
  expect(cold.model_versions.ranker).toBe('ranker:popularity:v1');
  await page.goto('/');
  const card = page.locator('.pin-card').first();
  await expect(card).toBeVisible();
  const title = (await card.getByRole('button', { name: /^Open / }).getAttribute('aria-label'))!.slice(5);
  const pinId = cold.items.find((item: { pin: { title: string } }) => item.pin.title === title).pin.id;
  await card.scrollIntoViewIfNeeded();
  // Wait for the actual 50%-visible/1-second view before expecting resolved history.
  await expect.poll(() => viewed.has(pinId)).toBeTruthy();
  const action = page.waitForResponse(r => r.url().endsWith('/api/events') &&
    r.request().postDataJSON()?.type === 'closeup');
  await card.getByRole('button', { name: /^Open / }).click();
  expect((await action).status()).toBe(200);
  await expect(page.getByRole('dialog', { name: title, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close dialog' }).click();
  const loaded = page.waitForResponse(r => r.url().includes('/api/feed') && r.request().method() === 'GET');
  await page.reload();
  const warm = await (await loaded).json();
  expect(warm.model_versions.ranker).toMatch(/^ranker:logreg:/);
  expect(warm.model_versions.ranker_sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(warm.model_versions.pin_embedder).toBe('embedder:clip-image-title:v1');
  await expect(page.locator('.pin-card').first()).toBeVisible();
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: `test-results/phase3-personalized-${test.info().project.name}.png`, fullPage: true });
});
