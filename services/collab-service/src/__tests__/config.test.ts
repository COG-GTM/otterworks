import { loadConfig, positiveInt } from '../config';

describe('positiveInt', () => {
  const NAME = 'YWS_TEST_LIMIT';

  afterEach(() => {
    delete process.env[NAME];
  });

  it('uses the default when unset', () => {
    expect(positiveInt(NAME, 42)).toBe(42);
  });

  it('parses valid positive integers', () => {
    process.env[NAME] = '1024';
    expect(positiveInt(NAME, 42)).toBe(1024);
  });

  it.each(['abc', '', '0', '-5', '1.5', 'NaN', '1e400'])(
    'falls back to the default for %p',
    (value) => {
      process.env[NAME] = value;
      expect(positiveInt(NAME, 42)).toBe(42);
    },
  );

  it('never yields NaN y-websocket limits', () => {
    process.env.YWS_MAX_DOC_BYTES = 'not-a-number';
    try {
      const { yWebsocket } = loadConfig();
      expect(yWebsocket.maxDocBytes).toBe(8388608);
      for (const value of Object.values(yWebsocket)) {
        expect(Number.isSafeInteger(value) && value > 0).toBe(true);
      }
    } finally {
      delete process.env.YWS_MAX_DOC_BYTES;
    }
  });
});
