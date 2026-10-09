import { buildRedisOptions } from '../services/redis-adapter';

describe('buildRedisOptions', () => {
  it('connects without TLS or AUTH to a local Redis by default', () => {
    const opts = buildRedisOptions({ host: 'redis', port: 6379 });

    expect(opts.tls).toBeUndefined();
    expect(opts.password).toBeUndefined();
  });

  it('uses TLS with SNI and the AUTH token for the shared ElastiCache', () => {
    const host = 'master.otterworks-redis-dev.cache.amazonaws.com';
    const opts = buildRedisOptions({ host, port: 6379, password: 's3cret', tls: true });

    expect(opts.tls).toEqual({ servername: host });
    expect(opts.password).toBe('s3cret');
  });
});
