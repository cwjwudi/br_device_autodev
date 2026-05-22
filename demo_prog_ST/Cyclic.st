
PROGRAM _CYCLIC

	CASE MachineState OF	
		STATE_WAIT:			
			IF EDGEPOS(boolStart) THEN;
				MachineState := STATE_HIDE_NEW_MATERIAL;
			END_IF;
		STATE_HIDE_NEW_MATERIAL:
			transform := '[{"select":".cNewMaterial","display":"false"}]';
			TIMER_TON(IN := TRUE , PT := WAIT_TIME);
			IF TIMER_TON.Q = TRUE THEN
				
				TIMER_TON(IN := FALSE);
				MachineState := STATE_REMOVE_PISTON;
			END_IF;	
		STATE_REMOVE_PISTON:
			transform := '[{"select":".cPiston","translate":[20,0]}]';
			TIMER_TON(IN := TRUE , PT := WAIT_TIME);
			IF TIMER_TON.Q = TRUE THEN
				
				TIMER_TON(IN := FALSE);
				MachineState := STATE_REMOVE_UNIT;
			END_IF;	
		STATE_REMOVE_UNIT:
			transform := '[{"select":".cInUnit","translate":[100,0]},{"select":".cPiston","translate":[120,0]},{"select":".cMeltedMaterial","translate":[100,0], "display":"true"}]';
			TIMER_TON(IN := TRUE , PT := WAIT_TIME);
			IF TIMER_TON.Q = TRUE THEN
				
				TIMER_TON(IN := FALSE);
				MachineState := STATE_REMOVE_CLAMP;
			END_IF;	
		STATE_REMOVE_CLAMP:
			transform := '[{"select":".cClamp","translate":[-100,0]}, {"select":".cPart","translate":[-100,0]}]';
			TIMER_TON(IN := TRUE , PT := WAIT_TIME);
			IF TIMER_TON.Q = TRUE THEN
				
				TIMER_TON(IN := FALSE);
				MachineState := STATE_REMOVE_PART_1;
			END_IF;	
		STATE_REMOVE_PART_1:
			transform := '[{"select":".cPart","translate":[-50,0]}]';
			TIMER_TON(IN := TRUE , PT := WAIT_TIME);
			IF TIMER_TON.Q = TRUE THEN
				
				TIMER_TON(IN := FALSE);
				MachineState := STATE_REMOVE_PART_2;
			END_IF;	
		STATE_REMOVE_PART_2:
			transform := '[{"select":".cPart","translate":[-50,350],"display":"false"}]';
			TIMER_TON(IN := TRUE , PT := WAIT_TIME);
			IF TIMER_TON.Q = TRUE THEN
				
				TIMER_TON(IN := FALSE);
				MachineState := STATE_APPLY_PART;
			END_IF;	
		STATE_APPLY_PART:
			transform := '[{"select":".cPart","translate":[0,0]}]';
			TIMER_TON(IN := TRUE , PT := WAIT_TIME / 4);
			IF TIMER_TON.Q = TRUE THEN
				
				TIMER_TON(IN := FALSE);
				MachineState := STATE_APPLY_CLAMP;
			END_IF;
		STATE_APPLY_CLAMP:
			transform := '[{"select":".cClamp","translate":[0,0]}]';
			TIMER_TON(IN := TRUE , PT := WAIT_TIME);
			IF TIMER_TON.Q = TRUE THEN
				
				TIMER_TON(IN := FALSE);
				MachineState := STATE_APPLY_UNIT;
			END_IF;
		STATE_APPLY_UNIT:
			transform := '[{"select":".cInUnit","translate":[0,0]},{"select":".cPiston","translate":[20,0]},{"select":".cMeltedMaterial","translate":[0,0]}]';
			TIMER_TON(IN := TRUE , PT := WAIT_TIME);
			IF TIMER_TON.Q = TRUE THEN
				
				TIMER_TON(IN := FALSE);
				MachineState := STATE_APPLY_PISTON;
			END_IF;
		STATE_APPLY_PISTON:
			transform := '[{"select":".cPiston","translate":[0,0]},{"select":".cMeltedMaterial", "display":"false"}, {"select":".cNewMaterial","display":"true"}]';
			TIMER_TON(IN := TRUE , PT := WAIT_TIME);
			IF TIMER_TON.Q = TRUE THEN
				
				TIMER_TON(IN := FALSE);
				MachineState := STATE_SHOW_PART;
			END_IF;
		STATE_SHOW_PART:
			transform := '[{"select":".cPart","display":"true"}]';
			TIMER_TON(IN := TRUE , PT := WAIT_TIME);
			IF TIMER_TON.Q = TRUE THEN
				
				TIMER_TON(IN := FALSE);
				
				boolStart := FALSE;
				MachineState := STATE_WAIT;
			END_IF;
	END_CASE;

	
	CASE SkiState OF	
		STATE_SKI_WAIT:
			transformSki := '';
			IF EDGEPOS(startSkiLift) THEN;
				SkiState := STATE_SKI_TOP;
			END_IF;
		STATE_SKI_TOP:
			transformSki := '[{"select":"#chairGroup","duration":3000,"display":true,"tPath":["#lift", true, 0, 28]},{"select":"#motorAxis","duration":3000,"spin":[720,0,0]}]';

			SKI_TIMER(IN := TRUE , PT := SKI_WAIT_TIME);
			IF SKI_TIMER.Q = TRUE THEN
				SKI_WAIT_TIME := T#5.80S;
				SKI_TIMER(IN := FALSE);
				SkiState := STATE_SKI_TURN;
			END_IF;	
		STATE_SKI_TURN:
			transformSki := '[{"select":"#chairGroup","duration":6000,"display":true,"tPath":["#lift", true, 28, 72]},{"select":"#motorAxis","duration":6000,"spin":[720,0,0]}, {"select":".person","duration":6000,"fill":1}]';

			SKI_TIMER(IN := TRUE , PT := SKI_WAIT_TIME);
			IF SKI_TIMER.Q = TRUE THEN
				SKI_WAIT_TIME := T#2.8S;
				SKI_TIMER(IN := FALSE);
				SkiState := STATE_SKI_BOTTOM;
			END_IF;	
		STATE_SKI_BOTTOM:
			transformSki := '[{"select":"#chairGroup","duration":3000,"display":false,"tPath":["#lift", true, 72, 100]},{"select":"#motorAxis","duration":3000,"spin":[720,0,0]}, {"select":".person","duration":3000,"fill":0}]';

			SKI_TIMER(IN := TRUE , PT := SKI_WAIT_TIME);
			IF SKI_TIMER.Q = TRUE THEN
				SKI_TIMER(IN := FALSE);
				startSkiLift := FALSE;
				SkiState := STATE_SKI_WAIT;
			END_IF;	
	END_CASE;
	
	CASE LiftState OF	
		STATE_INIT:			
			IF startBoxLift THEN;
				LiftState := STATE_SHOW_BOX;
			ELSE
				BOX_COUNTER := 0;
			END_IF;
		STATE_SHOW_BOX:
			IF BOX_COUNTER = 0 THEN
				transformLift := '[{"select":"#box_red_1","display":true,"duration":1000}]';
			ELSIF BOX_COUNTER = 1 THEN
				transformLift := '[{"select":"#box_blue_1","display":true,"duration":1000}]';
			ELSIF BOX_COUNTER = 2 THEN
				transformLift := '[{"select":"#box_green_1","display":true,"duration":1000}]';
			ELSIF BOX_COUNTER = 3 THEN
				transformLift := '[{"select":"#box_blue_2","display":true,"duration":1000}]';
			ELSIF BOX_COUNTER = 4 THEN
				transformLift := '[{"select":"#box_red_2","display":true,"duration":1000}]';
			ELSIF BOX_COUNTER = 5 THEN	
				transformLift := '[{"select":"#box_green_2","display":true,"duration":1000}]';
			END_IF;
			
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				LiftState := STATE_LIFT_MOVE_UP;
			END_IF;
		STATE_LIFT_MOVE_UP:
			
			IF BOX_COUNTER = 0 THEN
				transformLift := '[{"select":"#platform","duration":1000,"tPath":["#platform_lift",false,100,70]}]';
			ELSIF BOX_COUNTER = 1 THEN
				transformLift := '[{"select":"#platform","duration":1000,"tPath":["#platform_lift",false,100,31]}]';
			ELSIF BOX_COUNTER = 2 THEN
				transformLift := '[{"select":"#platform","duration":1000,"tPath":["#platform_lift",false,100,31]}]';
			ELSIF BOX_COUNTER = 3 THEN
				transformLift := '[{"select":"#platform","duration":1000,"tPath":["#platform_lift",false,100,31]}]';
			ELSIF BOX_COUNTER = 4 THEN
				transformLift := '[{"select":"#platform","duration":1000,"tPath":["#platform_lift",false,100,70]}]';
			ELSIF BOX_COUNTER = 5 THEN	
				transformLift := '[{"select":"#platform","duration":1000,"tPath":["#platform_lift",false,100,31]}]';
			END_IF;
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				LiftState := STATE_LIFT_OPEN_LEFT;
			END_IF;
		STATE_LIFT_OPEN_LEFT:
			transformLift := '[{"select":"#platform_left","display":false,"duration":1000}]';
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				LiftState := STATE_LIFT_MOVE_LEFT;
			END_IF;
		STATE_LIFT_MOVE_LEFT:
			
			IF BOX_COUNTER = 0 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[85.5,189]}]';
			ELSIF BOX_COUNTER = 1 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[85.5,120]}]';
			ELSIF BOX_COUNTER = 2 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[85.5,120]}]';
			ELSIF BOX_COUNTER = 3 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[85.5,120]}]';
			ELSIF BOX_COUNTER = 4 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[85.5,189]}]';
			ELSIF BOX_COUNTER = 5 THEN	
				transformLift := '[{"select":"#platform","duration":1000,"translate":[85.5,120]}]';
			END_IF;
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				LiftState := STATE_LIFT_CLOSE_LEFT;
			END_IF;
		STATE_LIFT_CLOSE_LEFT:
			transformLift := '[{"select":"#platform_left","display":true,"duration":1000}]';
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				LiftState := STATE_BOTH_MOVE_RIGHT;
			END_IF;
		STATE_BOTH_MOVE_RIGHT:
			IF BOX_COUNTER = 0 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,189]},{"select":"#box_red_1","duration":1000,"translate":[136.5,176]}]';
			ELSIF BOX_COUNTER = 1 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,120]},{"select":"#box_blue_1","duration":1000,"translate":[136.5,107]}]';
			ELSIF BOX_COUNTER = 2 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,120]},{"select":"#box_green_1","duration":1000,"translate":[136.5,107]}]';
			ELSIF BOX_COUNTER = 3 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,120]},{"select":"#box_blue_2","duration":1000,"translate":[136.5,107]}]';
			ELSIF BOX_COUNTER = 4 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,189]},{"select":"#box_red_2","duration":1000,"translate":[136.5,176]}]';
			ELSIF BOX_COUNTER = 5 THEN	
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,120]},{"select":"#box_green_2","duration":1000,"translate":[136.5,107]}]';
			END_IF;
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				LiftState := STATE_BOTH_MOVE_DOWN;
			END_IF;
		STATE_BOTH_MOVE_DOWN:
			IF BOX_COUNTER = 0 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,205.2]},{"select":"#box_red_1","duration":1000,"translate":[136.5,192.2]}]';
			ELSIF BOX_COUNTER = 1 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,138.2]},{"select":"#box_blue_1","duration":1000,"translate":[136.5,125.2]}]';
			ELSIF BOX_COUNTER = 2 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,138.2]},{"select":"#box_green_1","duration":1000,"translate":[136.5,125.2]}]';
			ELSIF BOX_COUNTER = 3 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,138.2]},{"select":"#box_blue_2","duration":1000,"translate":[136.5,125.2]}]';
			ELSIF BOX_COUNTER = 4 THEN
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,205.2]},{"select":"#box_red_2","duration":1000,"translate":[136.5,192.2]}]';
			ELSIF BOX_COUNTER = 5 THEN	
				transformLift := '[{"select":"#platform","duration":1000,"translate":[131,138.2]},{"select":"#box_green_2","duration":1000,"translate":[136.5,125.2]}]';
			END_IF;
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				LiftState := STATE_LIFT_OPEN_RIGHT;
			END_IF;
		STATE_LIFT_OPEN_RIGHT:
			transformLift := '[{"select":"#platform_right","display":false,"duration":1000}]';
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				LiftState := STATE_BOX_MOVE_RIGHT;
			END_IF;
		STATE_BOX_MOVE_RIGHT:
			IF BOX_COUNTER = 0 THEN
				transformLift := '[{"select":"#box_red_1","display":true,"duration":1000,"translate":[185,192.2]}]';
			ELSIF BOX_COUNTER = 1 THEN
				transformLift := '[{"select":"#box_blue_1","display":true,"duration":1000,"translate":[185,125.2]}]';
			ELSIF BOX_COUNTER = 2 THEN
				transformLift := '[{"select":"#box_green_1","display":true,"duration":1000,"translate":[185,125.2]}]';
			ELSIF BOX_COUNTER = 3 THEN
				transformLift := '[{"select":"#box_blue_2","display":true,"duration":1000,"translate":[185,125.2]}]';
			ELSIF BOX_COUNTER = 4 THEN
				transformLift := '[{"select":"#box_red_2","display":true,"duration":1000,"translate":[185,192.2]}]';
			ELSIF BOX_COUNTER = 5 THEN	
				transformLift := '[{"select":"#box_green_2","display":true,"duration":1000,"translate":[185,125.2]}]';
			END_IF;
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				LiftState := STATE_CONV_MOVE_RIGHT;
			END_IF;
		STATE_CONV_MOVE_RIGHT:
			IF BOX_COUNTER = 0 THEN
				transformLift := '[{"select":"#box_red_1","display":false,"duration":1000,"tPath":["#lowerConveyor",false,0,100]}]';
			ELSIF BOX_COUNTER = 1 THEN
				transformLift := '[{"select":"#box_blue_1","display":false,"duration":1000,"tPath":["#upperConveyor",false,0,100]}]';
			ELSIF BOX_COUNTER = 2 THEN
				transformLift := '[{"select":"#box_green_1","display":false,"duration":1000,"tPath":["#upperConveyor",false,0,100]}]';
			ELSIF BOX_COUNTER = 3 THEN
				transformLift := '[{"select":"#box_blue_2","display":false,"duration":1000,"tPath":["#upperConveyor",false,0,100]}]';
			ELSIF BOX_COUNTER = 4 THEN
				transformLift := '[{"select":"#box_red_2","display":false,"duration":1000,"tPath":["#lowerConveyor",false,0,100]}]';
			ELSIF BOX_COUNTER = 5 THEN	
				transformLift := '[{"select":"#box_green_2","display":false,"duration":1000,"tPath":["#upperConveyor",false,0,100]}]';
			END_IF;
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				LiftState := STATE_LIFT_CLOSE_RIGHT;
			END_IF;
		STATE_LIFT_CLOSE_RIGHT:
			transformLift := '[{"select":"#platform_right","display":true,"duration":1000}]';
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				LiftState := STATE_LIFT_BOX_INIT;
			END_IF;
		STATE_LIFT_BOX_INIT:	
			IF BOX_COUNTER = 0 THEN
				transformLift := '[{"select":"#box_red_1","duration":1000,"translate":[91,176]},{"select":"#platform","duration":1000,"translate":[131,240]}]';
			ELSIF BOX_COUNTER = 1 THEN
				transformLift := '[{"select":"#box_blue_1","duration":1000,"translate":[91,107]},{"select":"#platform","duration":1000,"translate":[131,240]}]';
			ELSIF BOX_COUNTER = 2 THEN
				transformLift := '[{"select":"#box_green_1","duration":1000,"translate":[91,107]},{"select":"#platform","duration":1000,"translate":[131,240]}]';
			ELSIF BOX_COUNTER = 3 THEN
				transformLift := '[{"select":"#box_blue_2","duration":1000,"translate":[91,107]},{"select":"#platform","duration":1000,"translate":[131,240]}]';
			ELSIF BOX_COUNTER = 4 THEN
				transformLift := '[{"select":"#box_red_2","duration":1000,"translate":[91,176]},{"select":"#platform","duration":1000,"translate":[131,240]}]';
			ELSIF BOX_COUNTER = 5 THEN	
				transformLift := '[{"select":"#box_green_2","duration":1000,"translate":[91,107]},{"select":"#platform","duration":1000,"translate":[131,240]}]';
			END_IF;
			TIMER_TON_LIFT(IN := TRUE , PT := WAIT_TIME_LIFT);
			IF TIMER_TON_LIFT.Q = TRUE THEN
				
				TIMER_TON_LIFT(IN := FALSE);
				BOX_COUNTER := BOX_COUNTER +1;
				IF BOX_COUNTER >= 6 THEN
					startBoxLift := FALSE;
				END_IF;
				LiftState := STATE_INIT;
			END_IF;
	END_CASE;
	
	 
END_PROGRAM
