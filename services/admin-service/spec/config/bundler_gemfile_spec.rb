require 'spec_helper'
require 'open3'
require 'rbconfig'
require 'tmpdir'

RSpec.describe 'config/bundler_gemfile' do
  let(:bundler_gemfile) { File.expand_path('../../config/bundler_gemfile.rb', __dir__) }
  let(:service_gemfile) { File.expand_path('../../Gemfile', __dir__) }
  let(:clean_env) { { 'BUNDLE_GEMFILE' => nil, 'RUBYOPT' => nil, 'BUNDLE_BIN_PATH' => nil } }

  def gemfile_after_require(env)
    out, err, status = Open3.capture3(env, RbConfig.ruby, '--disable-gems', '-e',
                                      'require ARGV[0]; print ENV["BUNDLE_GEMFILE"]',
                                      bundler_gemfile, chdir: Dir.tmpdir)
    expect(status).to be_success, err
    out
  end

  it 'defaults BUNDLE_GEMFILE to the service Gemfile when unset, regardless of cwd' do
    expect(gemfile_after_require(clean_env)).to eq(service_gemfile)
  end

  it 'keeps an explicitly set BUNDLE_GEMFILE' do
    expect(gemfile_after_require(clean_env.merge('BUNDLE_GEMFILE' => '/custom/Gemfile'))).to eq('/custom/Gemfile')
  end
end
