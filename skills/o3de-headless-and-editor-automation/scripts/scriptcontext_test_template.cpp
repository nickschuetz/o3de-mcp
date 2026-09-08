/*
 * Copyright (c) Contributors to the Open 3D Engine Project.
 * For complete copyright and license terms please see the LICENSE at the root of this distribution.
 *
 * SPDX-License-Identifier: Apache-2.0 OR MIT
 *
 */

// TEMPLATE: prove a reflected EBus/method/enum works from script, with no pixels.
// Adapted from a real, passing AzFramework test. Replace the placeholder bus with
// the one under test, add it to your module's *_tests_files.cmake, then run the
// REVERT-CYCLE (see reference/behavior-tests.md): it must FAIL without your
// reflection change and PASS with it.
//
// Build + run (from-source engine/fork):
//   cmake --build <build_dir> --config <cfg> --target <Module>.Tests
//   <build_dir>/bin/<cfg>/AzTestRunner \
//       "$(readlink -f <build_dir>/bin/<cfg>/lib<Module>.Tests.so)" \
//       AzRunUnitTests --gtest_filter='*ReflectionFromScript*'

#include <AzCore/Math/MathReflection.h>   // AZ::MathReflect -> Vector2/Vector3/Color
#include <AzCore/Math/Vector2.h>
#include <AzCore/RTTI/BehaviorContext.h>
#include <AzCore/Script/ScriptContext.h>
#include <AzCore/UnitTest/TestTypes.h>

// #include <YourModule/YourRequestBus.h>   // <-- the bus under test

namespace ReflectionFromScriptTemplate
{
    namespace
    {
        // Statics bridged to Lua via reflected properties so the script can hand
        // values back to the test for assertion.
        float g_capturedValue = -1.0f;
        bool g_busVisibleInLua = false;

        // Helper so Lua can extract a scalar from a returned math type without
        // depending on how that type is exposed to script.
        float ExtractVec2X(const AZ::Vector2& v)
        {
            return v.GetX();
        }

        // Stub handler: stand-in for the real backend, returns a known value.
        // class StubHandler : public YourRequestBus::Handler
        // {
        // public:
        //     void Connect()    { YourRequestBus::Handler::BusConnect(/* id */); }
        //     void Disconnect() { YourRequestBus::Handler::BusDisconnect(); }
        //     AZ::Vector2 GetSomething() const override { return AZ::Vector2(0.7f, 0.3f); }
        //     // ... implement the rest of the interface ...
        // };
    } // namespace

    class ReflectionFromScriptTest : public UnitTest::LeakDetectionFixture
    {
    protected:
        void SetUp() override
        {
            UnitTest::LeakDetectionFixture::SetUp();
            g_capturedValue = -1.0f;
            g_busVisibleInLua = false;

            m_behaviorContext = aznew AZ::BehaviorContext();

            // Reflect dependencies the binding needs (these are the usual trap):
            //  - math types for any Vector2/Color args or returns
            //  - the bus-id type for an EBus addressed by id (the Event(id) binding
            //    treats the bus address as an argument, so it must be reflected, or
            //    you get "argument type ... is not serialized and/or reflected").
            AZ::MathReflect(m_behaviorContext);
            // YourBusIdType::Reflect(m_behaviorContext);

            // The reflection under test:
            // YourComponentOrType::Reflect(m_behaviorContext);

            // Test-only bridges.
            m_behaviorContext->Method("ExtractVec2X", &ExtractVec2X);
            m_behaviorContext->Property("g_capturedValue", BehaviorValueProperty(&g_capturedValue));
            m_behaviorContext->Property("g_busVisibleInLua", BehaviorValueProperty(&g_busVisibleInLua));

            m_scriptContext = aznew AZ::ScriptContext();
            m_scriptContext->BindTo(m_behaviorContext);
        }

        void TearDown() override
        {
            delete m_scriptContext;
            m_scriptContext = nullptr;
            delete m_behaviorContext;
            m_behaviorContext = nullptr;
            UnitTest::LeakDetectionFixture::TearDown();
        }

        AZ::BehaviorContext* m_behaviorContext = nullptr;
        AZ::ScriptContext* m_scriptContext = nullptr;
    };

    // Tier 1: the bus/method/enum are registered in the BehaviorContext.
    TEST_F(ReflectionFromScriptTest, Reflected_Registration)
    {
        // auto it = m_behaviorContext->m_ebuses.find("YourRequestBus");
        // ASSERT_NE(it, m_behaviorContext->m_ebuses.end());
        // EXPECT_NE(it->second->m_events.find("GetSomething"), it->second->m_events.end());
        // EXPECT_NE(m_behaviorContext->m_properties.find("YourEnum_Value"),
        //           m_behaviorContext->m_properties.end());
        SUCCEED() << "fill in registration assertions for the bus under test";
    }

    // Tier 2: a gameplay-style Lua script can see and call it, end to end.
    TEST_F(ReflectionFromScriptTest, Reflected_CallableFromScript)
    {
        // StubHandler stub; stub.Connect();
        // const char* script =
        //     "g_busVisibleInLua = (YourRequestBus ~= nil)\n"
        //     "local v = YourRequestBus.Broadcast.GetSomething()\n"
        //     "g_capturedValue = ExtractVec2X(v)\n";
        // const bool executed = m_scriptContext->Execute(script);
        // stub.Disconnect();
        // EXPECT_TRUE(executed);
        // EXPECT_TRUE(g_busVisibleInLua);
        // EXPECT_NEAR(g_capturedValue, 0.7f, 0.0001f);
        SUCCEED() << "fill in the Lua call + assertions for the bus under test";
    }
} // namespace ReflectionFromScriptTemplate
