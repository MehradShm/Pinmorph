import { test, expect } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

// The generated PNG fixture contains no external/licensed content.
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAFAAAAB4CAIAAADqjOKhAAAA00lEQVR4nOXOQQEAIBCAMCSbAQxkeFucD5Zg69xNicRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjMRIjL8D0x50xwIAYAeqegAAAABJRU5ErkJggg==', 'base64');

test('sign up, upload, create board, save, remove, and sign in again', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const stamp = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const email = `browser-${stamp}@example.test`;
  const title = `Browser pin ${stamp}`;
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Find your next inspiration.' })).toBeVisible();
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByLabel('Your name').fill('Browser tester');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill('browser-password-123');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
  const account = await (await page.request.get('/api/auth/me')).json();
  const accountPath = test.info().outputPath('account.json');
  mkdirSync(dirname(accountPath), { recursive: true });
  writeFileSync(accountPath, JSON.stringify({ id: account.id, email: account.email }));

  await page.getByRole('button', { name: '+ Create pin', exact: true }).click();
  await page.getByLabel('Choose an image').setInputFiles({ name: 'demo.png', mimeType: 'image/png', buffer: png });
  await page.getByLabel('Title', { exact: true }).fill(title);
  await page.getByLabel('Description', { exact: true }).fill('An image uploaded through the real browser.');
  await page.getByLabel('Source link').fill('https://example.com/product');
  await page.getByRole('button', { name: 'Publish pin' }).click();
  await expect(page.getByRole('heading', { name: 'Your creations.' })).toBeVisible();
  const card = page.getByRole('button', { name: `Open ${title}`, exact: true });
  await expect(card.locator('img')).toBeVisible({ timeout: 30_000 });
  await card.click();
  const closeup = page.getByRole('dialog', { name: title, exact: true });
  await expect(closeup.getByRole('link', { name: 'Visit source' })).toHaveAttribute('href', 'https://example.com/product');
  await closeup.getByRole('button', { name: '+ Create a board' }).click();
  const boardDialog = page.getByRole('dialog', { name: 'Create a board', exact: true });
  await boardDialog.getByLabel('Board name').fill('Browser favorites');
  await boardDialog.getByRole('button', { name: 'Create board', exact: true }).click();
  await closeup.getByRole('button', { name: 'Save pin', exact: true }).click();
  await expect(closeup.getByRole('status')).toHaveText('Saved to Browser favorites');
  await closeup.getByRole('button', { name: 'Close dialog' }).click();
  await page.getByRole('button', { name: 'My boards', exact: true }).click();
  await page.getByRole('button', { name: /Browser favorites/ }).click();
  await expect(page.getByRole('button', { name: `Open ${title}` })).toBeVisible();
  await page.getByRole('button', { name: `Remove ${title} from board` }).click();
  await expect(page.getByRole('button', { name: `Open ${title}` })).toHaveCount(0);
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('button', { name: 'Already have an account? Sign in' }).click();
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill('browser-password-123');
  await page.getByRole('dialog').getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible();
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.screenshot({ path: `test-results/core-loop-${test.info().project.name}.png`, fullPage: true });
});

test('seeded catalog renders images and a shareable closeup', async ({ page }) => {
  await page.goto('/');
  const card = page.locator('.pin-card').filter({ has: page.locator('.demo-badge') }).first();
  await expect(card).toBeVisible();
  await expect(card.locator('img')).toBeVisible();
  await expect.poll(() => card.locator('img').evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
  await card.getByRole('button').click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page).toHaveURL(/#pin\//);
  await page.reload();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
