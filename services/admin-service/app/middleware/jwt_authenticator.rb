class JwtAuthenticator
  # Highest privilege first; used to pick one role when a token carries several.
  ROLE_PRECEDENCE = %w[owner super_admin admin editor viewer user].freeze

  EXCLUDED_PATHS = %w[/health /metrics /api/v1/admin/alerts/ingest /api/v1/admin/chaos].freeze

  def initialize(app)
    @app = app
  end

  def call(env)
    request = Rack::Request.new(env)

    return @app.call(env) if skip_authentication?(request)

    token = extract_token(request)
    return unauthorized_response('Missing authorization token') if token.nil?

    payload = decode_token(token)
    return unauthorized_response('Invalid or expired token') if payload.nil?

    env['jwt.payload'] = payload
    env['jwt.user_id'] = payload['sub']
    env['jwt.user_email'] = payload['email']
    env['jwt.user_role'] = extract_role(payload)

    @app.call(env)
  end

  private

  # auth-service issues a `roles` claim: an array of uppercase enum names
  # (USER, EDITOR, ADMIN, OWNER). Other issuers use a singular lowercase
  # `role` string. Normalize both shapes to one lowercase role, keeping the
  # highest-privilege entry when several are present.
  def extract_role(payload)
    roles = Array(payload['roles'])
    roles = [payload['role']] if roles.empty?
    normalized = roles.compact.map { |r| r.to_s.downcase }.reject(&:empty?)
    ROLE_PRECEDENCE.find { |r| normalized.include?(r) } || normalized.first
  end

  def skip_authentication?(request)
    EXCLUDED_PATHS.any? { |path| request.path == path }
  end

  def extract_token(request)
    header = request.env['HTTP_AUTHORIZATION']
    return nil unless header&.start_with?('Bearer ')

    header.split.last
  end

  def decode_token(token)
    secret = Rails.application.credentials.jwt_secret || ENV.fetch('JWT_SECRET', Rails.application.secrets.jwt_secret)
    # auth-service signs with HS512 (jjwt picks the algorithm from the key
    # length), so every real user token is rejected without it in this list.
    decoded = JWT.decode(token, secret, true, algorithms: %w[HS256 HS384 HS512])
    decoded.first
  rescue JWT::DecodeError, JWT::ExpiredSignature, JWT::VerificationError => e
    Rails.logger.warn("JWT authentication failed: #{e.message}")
    nil
  end

  def unauthorized_response(message)
    body = { error: message }.to_json
    [401, { 'Content-Type' => 'application/json' }, [body]]
  end
end
