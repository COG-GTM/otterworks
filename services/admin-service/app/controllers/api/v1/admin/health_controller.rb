module Api
  module V1
    module Admin
      class HealthController < ApplicationController
        before_action :require_admin!

        # GET /api/v1/admin/health/services
        def services
          result = HealthChecker.check_all

          render json: result, status: :ok
        end
      end
    end
  end
end
