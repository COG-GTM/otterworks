import { DocumentMemoryBudget } from '../services/memory-budget';

describe('DocumentMemoryBudget', () => {
  it('tracks per-key sizes and the running total', () => {
    const budget = new DocumentMemoryBudget(100);
    budget.set('a', 40);
    budget.set('b', 30);
    budget.set('a', 50);
    expect(budget.get('a')).toBe(50);
    expect(budget.total).toBe(80);
    budget.release('a');
    expect(budget.total).toBe(30);
    expect(budget.get('a')).toBe(0);
  });

  it('reports whether a resize would exceed the cap', () => {
    const budget = new DocumentMemoryBudget(100);
    budget.set('a', 60);
    budget.set('b', 30);
    expect(budget.wouldExceed('a', 70)).toBe(false);
    expect(budget.wouldExceed('a', 71)).toBe(true);
    expect(budget.wouldExceed('c', 11)).toBe(true);
    expect(budget.exceeded()).toBe(false);
    budget.set('c', 20);
    expect(budget.exceeded()).toBe(true);
  });
});
