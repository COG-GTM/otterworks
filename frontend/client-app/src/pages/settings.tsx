import { useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { User, Bell, Save } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { PageLoader } from "@/components/ui/loading-spinner";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { authApi, settingsApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";

const profileSchema = z.object({
  displayName: z.string().min(2, "Name must be at least 2 characters"),
  email: z.string().email("Please enter a valid email"),
});

type ProfileForm = z.infer<typeof profileSchema>;

export default function SettingsPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <SettingsContent />
      </ErrorBoundary>
    </AppShell>
  );
}

function SettingsContent() {
  const { user, setUser } = useAuthStore();
  const queryClient = useQueryClient();

  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: () => settingsApi.get(),
  });

  const profileMutation = useMutation({
    mutationFn: (data: ProfileForm) => authApi.updateProfile(data),
    onSuccess: (updatedUser) => {
      setUser(updatedUser);
    },
  });

  const settingsMutation = useMutation({
    mutationFn: (data: Partial<{ notificationEmail: boolean; notificationInApp: boolean; notificationDesktop: boolean }>) =>
      settingsApi.update(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const {
    register,
    handleSubmit,
    formState: { errors, isDirty },
    reset,
  } = useForm<ProfileForm>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      displayName: user?.displayName || "",
      email: user?.email || "",
    },
  });

  useEffect(() => {
    if (user) {
      reset({ displayName: user.displayName, email: user.email });
    }
  }, [user, reset]);

  if (settingsLoading) return <PageLoader />;

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <h1 className="text-2xl font-bold text-slate-100">Settings</h1>

      {/* Profile section */}
      <section className="bg-surface rounded-xl border border-line overflow-hidden">
        <div className="px-6 py-4 border-b border-line flex items-center gap-2">
          <User size={18} className="text-slate-400" />
          <h2 className="font-medium text-slate-100">Profile</h2>
        </div>
        <form onSubmit={handleSubmit((data) => profileMutation.mutate(data))} className="p-6 space-y-5">
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-slate-300 mb-1.5">
              Full name
            </label>
            <input
              id="name"
              type="text"
              {...register("displayName")}
              className="w-full px-3.5 py-2.5 bg-surface-raised border border-line rounded-lg text-sm text-slate-100 placeholder:text-slate-500 hover:border-line-strong focus:outline-none focus:ring-2 focus:ring-otter-400 focus:border-transparent transition"
            />
            {errors.displayName && (
              <p className="text-xs text-red-400 mt-1">{errors.displayName.message}</p>
            )}
          </div>

          <div>
            <label htmlFor="email" className="block text-sm font-medium text-slate-300 mb-1.5">
              Email
            </label>
            <input
              id="email"
              type="email"
              {...register("email")}
              className="w-full px-3.5 py-2.5 bg-surface-raised border border-line rounded-lg text-sm text-slate-100 placeholder:text-slate-500 hover:border-line-strong focus:outline-none focus:ring-2 focus:ring-otter-400 focus:border-transparent transition"
            />
            {errors.email && (
              <p className="text-xs text-red-400 mt-1">{errors.email.message}</p>
            )}
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={!isDirty || profileMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-otter-500 text-white rounded-lg hover:bg-otter-400 disabled:opacity-50 disabled:cursor-not-allowed transition text-sm font-medium"
            >
              <Save size={16} />
              {profileMutation.isPending ? "Saving..." : "Save changes"}
            </button>
          </div>

          {profileMutation.isSuccess && (
            <p className="text-sm text-green-400">Profile updated successfully.</p>
          )}
        </form>
      </section>

      {/* Notification preferences */}
      <section className="bg-surface rounded-xl border border-line overflow-hidden">
        <div className="px-6 py-4 border-b border-line flex items-center gap-2">
          <Bell size={18} className="text-slate-400" />
          <h2 className="font-medium text-slate-100">Notification preferences</h2>
        </div>
        <div className="p-6 space-y-4">
          <ToggleRow
            label="Email notifications"
            description="Receive notifications via email"
            checked={settings?.notificationEmail ?? true}
            onChange={(checked) =>
              settingsMutation.mutate({ notificationEmail: checked })
            }
          />
          <ToggleRow
            label="In-app notifications"
            description="Show notifications within the app"
            checked={settings?.notificationInApp ?? true}
            onChange={(checked) =>
              settingsMutation.mutate({ notificationInApp: checked })
            }
          />
          <ToggleRow
            label="Desktop notifications"
            description="Show browser push notifications"
            checked={settings?.notificationDesktop ?? false}
            onChange={(checked) =>
              settingsMutation.mutate({ notificationDesktop: checked })
            }
          />
        </div>
      </section>
    </div>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: Readonly<{
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}>) {
  return (
    <div className="flex items-center justify-between py-2">
      <div>
        <p className="text-sm font-medium text-slate-100">{label}</p>
        <p className="text-xs text-slate-400">{description}</p>
      </div>
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition focus:outline-none focus-visible:ring-2 focus-visible:ring-otter-400 ${
          checked ? "bg-otter-500" : "bg-line-strong"
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-slate-100 transition ${
            checked ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}
